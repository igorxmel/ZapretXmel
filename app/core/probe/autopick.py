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
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from app.core import ipset, paths, winws
from app.core.batfile import StrategySpec
from app.core.probe import dpi, services
from app.core.probe.dpi import DpiResult, DpiStatus, DpiTarget
from app.core.probe.services import Service, ServiceResult

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
    def working_services(self) -> list[str]:
        return [result.service for result in self.services if result.works]

    @property
    def broken_services(self) -> list[str]:
        return [result.service for result in self.services if not result.works]

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
        if self.services:
            working = self.working_services
            parts.insert(0, f"сервисов работает {len(working)} из {len(self.services)}")
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
            for result in score.services:
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
    score.median_ms = round(statistics.median(durations), 1) if durations else 0.0
    return score


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
    ) -> Report:
        """Перебирает стратегии и возвращает отчёт.

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

            for index, spec in enumerate(specs, start=1):
                if self.cancel.is_set():
                    report.cancelled = True
                    break

                self._say(on_progress, f"[{index}/{len(specs)}] {spec.name}")
                score = self._run_one(spec, chosen, dpi_targets, on_progress)
                report.scores.append(score)
                if on_strategy_done:
                    on_strategy_done(score)
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
        """Проверяет сервисы параллельно, сохраняя их исходный порядок."""
        results: list[ServiceResult] = []
        durations: list[float] = []

        with ThreadPoolExecutor(max_workers=self.parallel) as pool:
            futures = {
                pool.submit(services.check, service, self.timeout): service for service in chosen
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
