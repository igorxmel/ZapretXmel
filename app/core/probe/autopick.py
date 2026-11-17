"""Перебор стратегий с замером и выбором лучшей.

Нативная замена `utils/test zapret.ps1`: та же идея (поднять стратегию →
проверить → снять), но без консольных окон, с возможностью прервать прогон и
с историей, по которой видно, что работало у этого провайдера раньше.

Два отличия от апстрима определяют всё остальное.

**Замер без обхода** делается первым и служит точкой отсчёта. Без него легко
получить «победителя», который на самом деле просто ничего не сломал: у многих
провайдеров проверяемые адреса открываются и так.

**Счёт ведётся по сервисам, а не общей кучей.** Иначе стратегия, которая чинит
шесть проверок ютуба и роняет три проверки дискорда, обходит ту, что чинит оба
наполовину. Поэтому сначала сравнивается число полностью работающих сервисов,
и только потом общая сумма — а про сервисы, которые победитель так и не
починил, говорится прямо.
"""

from __future__ import annotations

import json
import logging
import statistics
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from app.core import ipset, paths, winws
from app.core.batfile import StrategySpec
from app.core.probe import dpi, services
from app.core.probe.dpi import DpiResult, DpiStatus, DpiTarget
from app.core.probe.services import CheckResult, Service, ServiceResult

log = logging.getLogger(__name__)

OnProgress = Callable[[str], None]
OnStrategyDone = Callable[["StrategyScore"], None]

Mode = Literal["services", "dpi"]

BASELINE_NAME = "без обхода"

# Сколько прогонов держим в истории. Подбор запускают помногу раз подряд, а
# каждый прогон — отдельный файл; старые отчёты не с чем сравнивать, потому
# что сборка за это время обновляется.
HISTORY_LIMIT = 30

# Сколько хостов из набора DPI проверять. Набор большой, а стратегий два
# десятка: брать его целиком — это часы прогона без выигрыша в точности.
DPI_TARGET_LIMIT = 10

# Сколько лидеров перепроверять. Один прогон — один замер, и место между близкими
# стратегиями решал случай: соседний сайт ответил на полсекунды позже, и только.
LEADERS_TO_RECHECK = 3

# Незаконченный подбор: файл переживает закрытие программы, и в следующий раз подбор
# продолжается с того места, где его прервали. Старше суток — сеть могла измениться.
PROGRESS_NAME = "autopick-unfinished.json"
PROGRESS_MAX_AGE_HOURS = 24

MODE_LABELS: dict[Mode, str] = {
    "services": "по сервисам",
    "dpi": "проверка DPI",
}


@dataclass
class StrategyScore:
    """Итог по одной стратегии."""

    name: str
    ok: int = 0
    error: int = 0
    blocked: int = 0
    median_ms: float = 0.0
    started: bool = True
    is_baseline: bool = False
    services: list[ServiceResult] = field(default_factory=list)
    dpi_results: list[DpiResult] = field(default_factory=list)

    @property
    def judged_services(self) -> list[ServiceResult]:
        """Сервисы, по которым можно судить об обходе.

        Группа из одних пингов одинакова у всех стратегий — winws к ICMP не
        прикасается. Победителя она не меняла, но попадала в «даже с ней не
        работает», и подбор заканчивался выговором за то, чего не чинит.
        Подробнее — в `services.Service.measures_bypass`.
        """
        return [result for result in self.services if result.measures_bypass]

    @property
    def working_services(self) -> list[str]:
        return [result.service for result in self.judged_services if result.works]

    @property
    def broken_services(self) -> list[str]:
        return [result.service for result in self.judged_services if not result.works]

    @property
    def sort_key(self) -> tuple[int, int, int, float]:
        """Сначала число целиком работающих сервисов, потом общая сумма проверок."""
        return (-len(self.working_services), -self.ok, self.blocked, self.median_ms or 9999.0)

    @property
    def services_label(self) -> str:
        return " · ".join(result.label for result in self.services) if self.services else "—"

    @property
    def summary(self) -> str:
        if not self.started:
            return "не запустилась"

        parts = [f"проверок пройдено {self.ok}"]
        if judged := self.judged_services:
            working = self.working_services
            parts.insert(0, f"сервисов работает {len(working)} из {len(judged)}")
        if self.error:
            parts.append(f"не прошло {self.error}")
        if self.blocked:
            parts.append(f"похоже на блокировку {self.blocked}")
        return ", ".join(parts)


@dataclass
class Report:
    """Результат целого прогона."""

    mode: Mode
    started_at: str
    finished_at: str
    checked: list[str]
    scores: list[StrategyScore] = field(default_factory=list)
    baseline: StrategyScore | None = None
    cancelled: bool = False
    # Остановился на первой стратегии, где работает всё, и сколько собирался проверить.
    stopped_early: bool = False
    planned: int = 0
    # Кого перепроверили вторым замером и сколько стратегий взято из прерванного подбора.
    rechecked: list[str] = field(default_factory=list)
    resumed: int = 0

    @property
    def strategies(self) -> list[StrategyScore]:
        return [score for score in self.scores if not score.is_baseline]

    @property
    def ranked(self) -> list[StrategyScore]:
        return sorted(self.strategies, key=lambda score: score.sort_key)

    @property
    def best_available(self) -> StrategyScore | None:
        """Лучшая по числам, даже если она не выиграла у базового замера."""
        workable = [score for score in self.strategies if score.started and score.ok > 0]
        return min(workable, key=lambda score: score.sort_key) if workable else None

    @property
    def best(self) -> StrategyScore | None:
        """Лучшая из стратегий, которая действительно обошла базовый замер."""
        candidate = self.best_available
        if candidate is None:
            return None
        if self.baseline is not None and not _beats(candidate, self.baseline):
            return None
        return candidate

    @property
    def service_winners(self) -> dict[str, str]:
        """Для каждого сервиса — стратегия, при которой он работает лучше всего.

        Сервисы отдаются от самого мелкого к крупному: у мелких фильтры обычно
        уже, и при сборке их секции должны встать раньше, иначе широкая секция
        крупного сервиса их затенит.
        """
        winners: dict[str, tuple[int, str]] = {}

        for score in self.strategies:
            if not score.started:
                continue
            for result in score.judged_services:
                best = winners.get(result.service)
                if best is None or result.ok_count > best[0]:
                    winners[result.service] = (result.ok_count, score.name)

        sizes = {
            result.service: result.total
            for score in self.strategies
            for result in score.services
        }
        ordered = sorted(winners, key=lambda service: sizes.get(service, 0))
        return {service: winners[service][1] for service in ordered if winners[service][0] > 0}

    @property
    def verdict(self) -> str:
        """Человеческий вывод из прогона — в том числе неприятный."""
        if not self.scores:
            return "Прогон не дал результатов."

        baseline, best = self.baseline, self.best

        if best is not None:
            text = f"Лучшая стратегия: «{best.name}» — {best.summary}."
            if broken := best.broken_services:
                text += (
                    " Но даже с ней не работает: "
                    + ", ".join(broken)
                    + ". Попробуйте режим «Проверка DPI» или добавьте свои цели."
                )
            else:
                text += " Все проверенные сервисы работают."
            if len(self.rechecked) > 1:
                text += (
                    f" Лидеров ({len(self.rechecked)}) проверил второй раз: проверка "
                    "засчитана, только если прошла оба раза."
                )
            if self.stopped_early:
                text += (
                    f" Подбор остановился на ней: проверено {len(self.strategies)} "
                    f"из {self.planned}."
                )
            return text

        if baseline is not None and not baseline.broken_services and baseline.ok > 0:
            return (
                "Блокировки не обнаружено: без обхода уже работает всё, что проверялось. "
                "Победителя тут быть не может — любая стратегия в лучшем случае не мешает. "
                "Если что-то всё равно не работает, добавьте это в свои цели или "
                "прогоните режим «Проверка DPI»."
            )

        if (fallback := self.best_available) is not None:
            return (
                "Ни одна стратегия не улучшила результат по сравнению с замером без обхода. "
                f"Самая безвредная — «{fallback.name}», она хотя бы ничего не ломает."
            )

        return (
            "Ни одна стратегия не дала рабочего результата. Загляните в «Диагностику» — "
            "скорее всего, мешает что-то в системе."
        )


def _beats(candidate: StrategyScore, baseline: StrategyScore) -> bool:
    """Стратегия выигрышна, если починила сервис или прошло больше проверок."""
    if len(candidate.working_services) > len(baseline.working_services):
        return True
    if candidate.ok > baseline.ok:
        return True
    return candidate.ok == baseline.ok and candidate.blocked < baseline.blocked


def build_services_score(
    name: str, results: list[ServiceResult], durations: list[float], is_baseline: bool = False
) -> StrategyScore:
    """Сворачивает результаты по сервисам в счёт."""
    score = StrategyScore(name=name, services=results, is_baseline=is_baseline)
    for result in results:
        score.ok += result.ok_count
        score.error += result.total - result.ok_count
    if not durations:
        # Время прошедших проб: у непрошедшей это таймаут, о скорости он ничего не говорит.
        durations = [
            check.elapsed_ms
            for result in results
            if result.measures_bypass
            for check in result.checks
            if check.ok and check.elapsed_ms > 0
        ]
    score.median_ms = round(statistics.median(durations), 1) if durations else 0.0
    return score


def combine(first: StrategyScore, second: StrategyScore) -> StrategyScore:
    """Два замера одной стратегии в один: проверка засчитана, только если прошла оба раза.

    Так случайная удача одного замера не выводит стратегию в лидеры, а время —
    медиана по обоим.
    """
    later = {result.service: result for result in second.services}
    merged: list[ServiceResult] = []
    for result in first.services:
        again = {check.name: check for check in later.get(result.service, result).checks}
        checks = []
        for check in result.checks:
            twin = again.get(check.name, check)
            times = [t for t in (check.elapsed_ms, twin.elapsed_ms) if t > 0 and check.ok]
            checks.append(
                replace(
                    check,
                    ok=check.ok and twin.ok,
                    elapsed_ms=round(statistics.median(times), 1) if times else 0.0,
                )
            )
        merged.append(replace(result, checks=checks))
    return build_services_score(first.name, merged, [], is_baseline=first.is_baseline)


def leaders(report: Report, limit: int = LEADERS_TO_RECHECK) -> list[StrategyScore]:
    """Стратегии, между которыми выбор не очевиден: столько же целых сервисов, как у первой."""
    ranked = [score for score in report.ranked if score.started and score.ok > 0]
    if len(ranked) < 2:
        return []
    top = len(ranked[0].working_services)
    close = [score for score in ranked if len(score.working_services) == top]
    return close[:limit] if len(close) > 1 else []


def build_dpi_score(
    name: str, results: list[DpiResult], is_baseline: bool = False
) -> StrategyScore:
    """Сворачивает проверку передачи данных в счёт."""
    score = StrategyScore(name=name, dpi_results=results, is_baseline=is_baseline)
    durations: list[float] = []

    for result in results:
        for line in result.lines:
            if line.status is DpiStatus.OK:
                score.ok += 1
                if line.seconds > 0:
                    durations.append(line.seconds * 1000)
            elif line.status is DpiStatus.LIKELY_BLOCKED:
                score.blocked += 1
                score.error += 1
            elif line.status is not DpiStatus.UNSUPPORTED:
                score.error += 1

    score.median_ms = round(statistics.median(durations), 1) if durations else 0.0
    return score


class AutoPicker:
    """Прогон стратегий с возможностью отмены."""

    def __init__(
        self,
        mode: Mode = "services",
        timeout: int = 6,
        parallel: int = 8,
        dpi_limit: int = DPI_TARGET_LIMIT,
    ):
        self.mode = mode
        self.timeout = timeout
        self.parallel = max(1, parallel)
        self.dpi_limit = dpi_limit
        self.cancel = threading.Event()
        self._payload: Path | None = None

    def stop(self) -> None:
        self.cancel.set()

    def run(
        self,
        specs: list[StrategySpec],
        chosen: list[Service] | None = None,
        dpi_targets: list[DpiTarget] | None = None,
        on_progress: OnProgress | None = None,
        on_strategy_done: OnStrategyDone | None = None,
        stop_when: Callable[[StrategyScore], bool] | None = None,
        done: list[StrategyScore] | None = None,
        on_checkpoint: Callable[[Report], None] | None = None,
    ) -> Report:
        """Перебирает стратегии и возвращает отчёт.

        `stop_when` останавливает перебор на первой стратегии, для которой он верен, —
        обычно «работает всё». Замер без обхода под него не попадает.

        `done` — стратегии, уже проверенные прерванным подбором: их не гоняем заново, а
        берём как есть. Замер без обхода всё равно делается свежий. `on_checkpoint`
        получает отчёт после каждой стратегии — чтобы сохранить ход подбора.

        Чужие запущенные экземпляры winws и режим ipset восстанавливаются в
        исходное состояние, даже если прогон прервали.
        """
        self.cancel.clear()
        chosen = chosen or []
        dpi_targets = dpi_targets or []
        is_dpi = self.mode == "dpi"

        foreign = winws.find_instances()
        original_ipset = ipset.status()
        report = Report(
            mode=self.mode,
            started_at=datetime.now().isoformat(timespec="seconds"),
            finished_at="",
            checked=[t.id for t in dpi_targets[: self.dpi_limit]]
            if is_dpi
            else [service.name for service in chosen],
            planned=len(specs),
        )

        try:
            if is_dpi:
                self._payload = dpi.make_payload()
                if original_ipset != "any":
                    self._say(on_progress, "Временно перевожу ipset в режим «любые адреса»")
                    ipset.set_mode("any")

            self._say(on_progress, "Замеряю, как всё работает без обхода…")
            winws.kill_all()
            baseline = self._measure(chosen, dpi_targets, BASELINE_NAME, is_baseline=True)
            report.baseline = baseline
            report.scores.append(baseline)
            if on_strategy_done:
                on_strategy_done(baseline)

            earlier = {score.name: score for score in done or [] if not score.is_baseline}
            for index, spec in enumerate(specs, start=1):
                if self.cancel.is_set():
                    report.cancelled = True
                    break

                if (score := earlier.get(spec.name)) is not None:
                    report.resumed += 1
                else:
                    self._say(on_progress, f"[{index}/{len(specs)}] {spec.name}")
                    score = self._run_one(spec, chosen, dpi_targets, on_progress)
                report.scores.append(score)
                if on_strategy_done:
                    on_strategy_done(score)
                if on_checkpoint:
                    on_checkpoint(report)
                if stop_when is not None and score.started and stop_when(score):
                    report.stopped_early = index < len(specs)
                    break

            # Перепроверка — только в полном прогоне: с галочкой «до первой рабочей»
            # человек просил скорость, а не точное место в таблице.
            if stop_when is None and not (is_dpi or report.cancelled):
                self._recheck_leaders(report, specs, chosen, dpi_targets, on_progress)
        finally:
            winws.kill_all()
            if is_dpi and original_ipset != "any":
                ipset.set_mode(original_ipset)
            if self._payload is not None:
                self._payload.unlink(missing_ok=True)
                self._payload = None
            if foreign:
                self._say(on_progress, "Возвращаю ранее запущенные экземпляры winws")
                winws.restore(foreign)

        report.finished_at = datetime.now().isoformat(timespec="seconds")
        return report

    def _recheck_leaders(
        self,
        report: Report,
        specs: list[StrategySpec],
        chosen: list[Service],
        dpi_targets: list[DpiTarget],
        on_progress: OnProgress | None,
    ) -> None:
        """Второй замер близких лидеров: место между ними не должно решать везение."""
        by_name = {spec.name: spec for spec in specs}
        close = [score for score in leaders(report) if score.name in by_name]
        for number, first in enumerate(close, start=1):
            if self.cancel.is_set():
                return
            self._say(on_progress, f"Перепроверяю лидеров [{number}/{len(close)}]: {first.name}")
            second = self._run_one(by_name[first.name], chosen, dpi_targets, on_progress)
            if not second.started:
                continue
            position = report.scores.index(first)
            report.scores[position] = combine(first, second)
            report.rechecked.append(first.name)

    def _measure(
        self,
        chosen: list[Service],
        dpi_targets: list[DpiTarget],
        name: str,
        is_baseline: bool = False,
    ) -> StrategyScore:
        if self.mode == "dpi":
            return build_dpi_score(name, self._check_dpi(dpi_targets), is_baseline=is_baseline)

        results, durations = self._check_services(chosen)
        return build_services_score(name, results, durations, is_baseline=is_baseline)

    def _run_one(
        self,
        spec: StrategySpec,
        chosen: list[Service],
        dpi_targets: list[DpiTarget],
        on_progress: OnProgress | None,
    ) -> StrategyScore:
        winws.kill_all()
        process = winws.WinwsProcess()

        try:
            process.start(spec)
        except (OSError, RuntimeError) as error:
            log.warning("Стратегия %s не запустилась: %s", spec.name, error)
            return StrategyScore(name=spec.name, started=False)

        try:
            if not winws.wait_until_ready():
                self._say(on_progress, f"  {spec.name}: процесс winws не появился")
                return StrategyScore(name=spec.name, started=False)
            return self._measure(chosen, dpi_targets, spec.name)
        finally:
            process.stop()
            winws.kill_all()

    def _check_services(
        self, chosen: list[Service]
    ) -> tuple[list[ServiceResult], list[float]]:
        """Проверяет сервисы параллельно, сохраняя их исходный порядок.

        Адреса внутри сервиса — тоже параллельно. По очереди они шли ради времени
        ответа, сравнимого между стратегиями, но оно в оценку не попадает. А ждать
        приходилось по таймауту на каждый закрытый адрес подряд: стратегия, которая
        что-то не пропускала, проверялась до 45 секунд вместо 10.
        """
        results: list[ServiceResult] = []
        durations: list[float] = []

        with ThreadPoolExecutor(max_workers=self.parallel) as pool:
            futures = {
                pool.submit(services.check, service, self.timeout, self.parallel): service
                for service in chosen
            }
            for future, service in futures.items():
                if self.cancel.is_set():
                    future.cancel()
                    continue
                try:
                    results.append(future.result())
                except Exception:  # noqa: BLE001 — один упавший сервис не рушит прогон
                    log.exception("Проверка сервиса %s завершилась ошибкой", service.name)

        order = {service.name: index for index, service in enumerate(chosen)}
        results.sort(key=lambda result: order.get(result.service, 0))
        return results, durations

    def _check_dpi(self, targets: list[DpiTarget]) -> list[DpiResult]:
        payload = self._payload
        if payload is None:
            return []

        selected = targets[: self.dpi_limit]
        results: list[DpiResult] = []
        with ThreadPoolExecutor(max_workers=self.parallel) as pool:
            futures = {
                pool.submit(dpi.check_target, target, payload, timeout=self.timeout): target
                for target in selected
            }
            for future, target in futures.items():
                if self.cancel.is_set():
                    future.cancel()
                    continue
                try:
                    results.append(future.result())
                except Exception:  # noqa: BLE001 — одна упавшая цель не рушит прогон
                    log.exception("Проверка цели %s завершилась ошибкой", target.id)

        order = {target.id: index for index, target in enumerate(selected)}
        results.sort(key=lambda result: order.get(result.target.id, 0))
        return results

    @staticmethod
    def _say(on_progress: OnProgress | None, message: str) -> None:
        log.info(message)
        if on_progress:
            on_progress(message)


def save_report(report: Report) -> Path:
    """Складывает отчёт в историю, чтобы можно было сравнить прогоны между собой."""
    paths.history_dir().mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = paths.history_dir() / f"autopick-{stamp}.json"

    best = report.best
    payload = {
        "mode": report.mode,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "cancelled": report.cancelled,
        "checked": report.checked,
        "best": best.name if best else "",
        "verdict": report.verdict,
        "scores": [
            {
                **{
                    key: value
                    for key, value in asdict(score).items()
                    # Подробности проб в историю не пишем — слишком объёмно.
                    if key not in ("services", "dpi_results")
                },
                "services": [result.label for result in score.services],
            }
            for score in [report.baseline, *report.ranked]
            if score is not None
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    prune_history()
    return path


def prune_history(keep: int = HISTORY_LIMIT) -> int:
    """Оставляет только последние прогоны. Возвращает число удалённых.

    Каждый прогон — отдельный файл, и подбор запускают помногу раз подряд,
    подбирая стратегию. Без прополки папка растёт бесконечно, а смысла в
    отчётах полугодовой давности нет: сборка за это время обновится, и
    сравнивать будет не с чем.
    """
    directory = paths.history_dir()
    if not directory.is_dir():
        return 0

    reports = sorted(directory.glob("autopick-*.json"), reverse=True)
    removed = 0
    for stale in reports[keep:]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            log.debug("Не удалось удалить старый отчёт %s", stale.name)

    if removed:
        log.info("Из истории подбора удалено отчётов: %s", removed)
    return removed


def load_history(limit: int = 20) -> list[dict]:
    """Последние прогоны, новые первыми."""
    directory = paths.history_dir()
    if not directory.is_dir():
        return []

    entries: list[dict] = []
    for path in sorted(directory.glob("autopick-*.json"), reverse=True)[:limit]:
        try:
            entries.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return entries


# --- незаконченный подбор ------------------------------------------------------


def progress_file() -> Path:
    return paths.data_dir() / PROGRESS_NAME


def save_progress(report: Report, strategies: list[str]) -> None:
    """Ход подбора по сервисам: сколько стратегий проверено и с какими итогами.

    Пишется после каждой стратегии. Подбор идёт минутами, и закрытие программы, сон
    ноутбука или «Остановить» на середине раньше обнуляли всё сделанное.
    """
    if report.mode != "services":
        return
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": report.started_at,
        "checked": report.checked,
        "strategies": strategies,
        "scores": [asdict(score) for score in report.strategies],
    }
    try:
        progress_file().parent.mkdir(parents=True, exist_ok=True)
        progress_file().write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as error:
        log.warning("Ход подбора не сохранён: %s", error)


def clear_progress() -> None:
    try:
        progress_file().unlink(missing_ok=True)
    except OSError:
        log.debug("Файл хода подбора занят")


@dataclass
class Unfinished:
    """Прерванный подбор, который можно продолжить."""

    checked: list[str]
    strategies: list[str]
    scores: list[StrategyScore]

    @property
    def done(self) -> int:
        return len(self.scores)

    @property
    def total(self) -> int:
        return len(self.strategies)


def _score_from(data: dict) -> StrategyScore:
    results = [
        ServiceResult(
            service=item["service"],
            checks=[CheckResult(**check) for check in item.get("checks", [])],
            measures_bypass=item.get("measures_bypass", True),
        )
        for item in data.get("services", [])
    ]
    fields = {key: data[key] for key in ("name", "ok", "error", "blocked", "median_ms", "started")
              if key in data}
    return StrategyScore(**fields, services=results)


def load_progress(strategies: list[str], now: datetime | None = None) -> Unfinished | None:
    """Прерванный подбор, если его ещё можно продолжить.

    Нельзя, если набор стратегий с тех пор поменялся (обновилось ядро, добавили свою)
    или прошло больше суток: результаты тогда описывают уже другую картину.
    """
    path = progress_file()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        saved = datetime.fromisoformat(data["saved_at"])
        unfinished = Unfinished(
            checked=list(data["checked"]),
            strategies=list(data["strategies"]),
            scores=[_score_from(item) for item in data["scores"]],
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        log.info("Ход подбора не прочитан, начнём заново: %s", error)
        clear_progress()
        return None

    age = (now or datetime.now()) - saved
    if age.total_seconds() > PROGRESS_MAX_AGE_HOURS * 3600 or sorted(
        unfinished.strategies
    ) != sorted(strategies):
        clear_progress()
        return None
    if not unfinished.scores or unfinished.done >= unfinished.total:
        return None
    return unfinished
