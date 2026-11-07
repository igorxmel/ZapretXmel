"""Журнал стабильности стратегий.

Подбор отвечает на вопрос «что работает сейчас», а человеку важно ещё «что не отвалится
через час». Сторож и так регулярно проверяет обход, поэтому результаты достаточно
запоминать. Журнал лежит только на этом компьютере и никуда не отправляется.

Считаются только последние две недели. Вечный счёт врал: провайдер поменял правила, стратегия
перестала работать, а оценка почти не менялась, потому что за ней стояли сотни старых удачных
проверок. По той же причине журнал начинается заново, когда меняется сам файл стратегии:
обновление ядра может оставить имя `general (ALT13)`, а аргументы поменять.

Каждая проверка помнит ещё и сервисы: какие работали, какие нет. Общая доля «прошла целиком»
скрывает, что стратегия держит Discord, а YouTube у неё отваливается, — а это и есть то, что
нужно знать при починке.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from app.core import paths

log = logging.getLogger(__name__)

FILENAME = "stability.json"
# Меньше этого о стратегии ещё ничего не известно: две удачные проверки подряд не лучше ста.
ENOUGH_CHECKS = 5
# За какой срок считаем. Две недели: и выходные попадают, и старые правила провайдера уходят.
WINDOW = timedelta(days=14)
# Предел на случай сторожа с интервалом в минуту: две недели таких проверок — двадцать тысяч строк.
MAX_ENTRIES = 2000
# Оценка стратегии, о которой ничего не известно: ниже проверенной, выше заведомо плохой.
UNKNOWN = 0.5

# Совет переключиться: сколько проверок нужно у обеих стратегий и насколько другая лучше.
ADVICE_CHECKS = 20
ADVICE_GAP = 0.15
# Выше этого включённая стратегия хороша сама по себе, и советовать незачем.
ADVICE_ENOUGH = 0.9

# Сбои по времени суток: минимум провалов, чтобы о закономерности вообще говорить.
DAYTIME_FAILURES = 4


@dataclass
class Entry:
    moment: datetime
    ok: bool
    working: list[str]
    broken: list[str]


@dataclass
class Record:
    # Проверки за последние две недели: [время, прошла ли, работавшие сервисы, сломанные].
    history: list[list] = field(default_factory=list)
    # С какого момента стратегия работает без сбоев. Пусто — сейчас она не работает.
    working_since: str = ""
    # Отпечаток файла стратегии, на котором собраны эти проверки.
    fingerprint: str = ""

    def entries(self, now: datetime | None = None) -> list[Entry]:
        edge = (now or datetime.now()) - WINDOW
        found = []
        for raw in self.history:
            moment = datetime.fromisoformat(raw[0])
            if moment < edge:
                continue
            working = list(raw[2]) if len(raw) > 2 else []
            broken = list(raw[3]) if len(raw) > 3 else []
            found.append(Entry(moment, bool(raw[1]), working, broken))
        return found

    def recent(self, now: datetime | None = None) -> list[bool]:
        return [entry.ok for entry in self.entries(now)]

    @property
    def checks(self) -> int:
        return len(self.history)

    @property
    def passed(self) -> int:
        return sum(1 for raw in self.history if raw[1])

    @property
    def rate(self) -> float:
        return self.passed / self.checks if self.checks else 0.0


def score(passed: int, total: int) -> float:
    """Оценка с поправкой на число проверок: нижняя граница интервала Уилсона.

    Простая доля ставит 5 из 5 вровень со 500 из 500, хотя о первой известно куда меньше. Нижняя
    граница растёт вместе с числом проверок: 5 из 5 дают около 0,57, 500 из 500 — почти единицу.
    """
    if total < ENOUGH_CHECKS:
        return UNKNOWN
    z = 1.96
    rate = passed / total
    middle = rate + z * z / (2 * total)
    spread = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
    return (middle - spread) / (1 + z * z / total)


def _file():
    return paths.data_dir() / FILENAME


def fingerprint(strategy: str) -> str:
    """Отпечаток `.bat` стратегии. Пусто, если файла нет: тогда и сравнивать не с чем."""
    try:
        content = (paths.core_dir() / f"{strategy}.bat").read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(content).hexdigest()[:16]


def load() -> dict[str, Record]:
    """Журнал целиком. Испорченный файл — не повод ломать опрос."""
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
        records: dict[str, Record] = {}
        for name, values in raw.items():
            if "history" not in values:
                # Вечный счёт прежних версий: перевести его в проверки по времени нельзя, а
                # дотянуть до новых он и не стоит — именно его неточность и чинили.
                continue
            records[name] = Record(
                history=list(values["history"]),
                working_since=values.get("working_since", ""),
                fingerprint=values.get("fingerprint", ""),
            )
        return records
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError, AttributeError, KeyError, IndexError):
        log.warning("Журнал стабильности не прочитан, начинаю заново")
        return {}


def _save(records: dict[str, Record]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    data = {name: asdict(record) for name, record in records.items()}
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, path)


def _current(name: str, item: Record | None) -> Record | None:
    """Запись, если она ещё про этот файл стратегии. Иначе о стратегии ничего не известно."""
    if item is None or not item.fingerprint:
        return item
    actual = fingerprint(name)
    return item if not actual or actual == item.fingerprint else None


def record(
    strategy: str,
    works: bool,
    now: datetime | None = None,
    working: list[str] | None = None,
    broken: list[str] | None = None,
) -> None:
    """Запоминает одну проверку работающей стратегии."""
    if not strategy:
        return

    moment = now or datetime.now()
    stamp = moment.isoformat(timespec="seconds")
    records = load()
    actual = fingerprint(strategy)
    item = records.get(strategy)
    if item is not None and actual and item.fingerprint and item.fingerprint != actual:
        log.info("Стратегия %s изменилась, журнал её стабильности начат заново", strategy)
        item = None
    item = item or Record()
    item.fingerprint = actual or item.fingerprint

    edge = moment - WINDOW
    item.history = [
        entry for entry in item.history if datetime.fromisoformat(entry[0]) >= edge
    ][-(MAX_ENTRIES - 1):]
    item.history.append([stamp, works, list(working or []), list(broken or [])])
    if works:
        item.working_since = item.working_since or stamp
    else:
        item.working_since = ""
    records[strategy] = item

    try:
        _save(records)
    except OSError:
        log.info("Журнал стабильности не записан", exc_info=True)


# --- чтение ---------------------------------------------------------------------


def _entries(name: str, records: dict[str, Record], now: datetime) -> list[Entry]:
    item = _current(name, records.get(name))
    return item.entries(now) if item is not None else []


def services(strategy: str, now: datetime | None = None) -> dict[str, tuple[int, int]]:
    """По каждому сервису: сколько раз работал и сколько раз проверялся."""
    counts: dict[str, list[int]] = {}
    for entry in _entries(strategy, load(), now or datetime.now()):
        for name in entry.working:
            counts.setdefault(name, [0, 0])[0] += 1
            counts[name][1] += 1
        for name in entry.broken:
            counts.setdefault(name, [0, 0])[1] += 1
    return {name: (passed, total) for name, (passed, total) in counts.items()}


def describe_services(strategy: str, now: datetime | None = None) -> str:
    """«Discord 100% · YouTube 71%». Сервисы с малым числом проверок не показываем."""
    parts = [
        f"{name} {round(passed / total * 100)}%"
        for name, (passed, total) in sorted(services(strategy, now).items())
        if total >= ENOUGH_CHECKS
    ]
    return " · ".join(parts)


def failure_hours(entries: list[Entry]) -> tuple[int, int] | None:
    """Часы, на которые приходится большинство сбоев, если такая закономерность есть.

    Многие провайдеры строже вечером. Без этой подсказки «прошла 70%» читается как «стратегия
    плохая», хотя днём она держит всё. Ищем самое короткое окно от трёх до шести часов, где
    не меньше четырёх пятых всех сбоев и где проверки проваливались хотя бы вдвое чаще, чем в
    остальное время. С порогом в две трети окно с 19 до 23 часов называлось «с 19 до 22»: три
    часа из четырёх уже набирали нужную долю.
    """
    failures = [entry.moment.hour for entry in entries if not entry.ok]
    if len(failures) < DAYTIME_FAILURES:
        return None
    hours = [entry.moment.hour for entry in entries]

    for length in range(3, 7):
        best = None
        for start in range(24):
            inside = {(start + step) % 24 for step in range(length)}
            failed_in = sum(1 for hour in failures if hour in inside)
            checked_in = sum(1 for hour in hours if hour in inside)
            failed_out = len(failures) - failed_in
            checked_out = len(hours) - checked_in
            if failed_in * 5 < len(failures) * 4 or not checked_in:
                continue
            rate_in = failed_in / checked_in
            rate_out = failed_out / checked_out if checked_out else 0.0
            if rate_in < 2 * rate_out:
                continue
            if best is None or failed_in > best[0]:
                best = (failed_in, start)
        if best is not None:
            return best[1], (best[1] + length) % 24
    return None


def describe(strategy: str, now: datetime | None = None) -> str:
    """Подпись для экрана стратегий."""
    now = now or datetime.now()
    records = load()
    entries = _entries(strategy, records, now)
    if not entries:
        return "пока не проверялась"

    oldest = min(entry.moment for entry in entries)
    days = math.ceil((now - oldest).total_seconds() / 86400)
    span = "за сутки" if days <= 1 else f"за {days} дн."
    passed = sum(1 for entry in entries if entry.ok)
    text = f"прошла {passed} из {len(entries)} проверок {span}"

    item = records[strategy]
    if item.working_since:
        since = datetime.fromisoformat(item.working_since)
        hours = int((now - since).total_seconds() // 3600)
        if hours >= 48:
            text += f", без сбоев {hours // 24} дн."
        elif hours >= 1:
            text += f", без сбоев {hours} ч."
    return text


def describe_hours(strategy: str, now: datetime | None = None) -> str:
    """«с 19:00 до 23:00», если сбои собираются в эти часы. Отдельной строкой: в общей подписи
    она не помещалась в ширину карточки."""
    window = failure_hours(_entries(strategy, load(), now or datetime.now()))
    return f"в основном с {window[0]:02d}:00 до {window[1]:02d}:00" if window else ""


def marks(names: list[str], now: datetime | None = None) -> dict[str, str]:
    """Короткая отметка для списков: «98%». Пусто, пока проверок мало."""
    now = now or datetime.now()
    records = load()
    found = {}
    for name in names:
        recent = [entry.ok for entry in _entries(name, records, now)]
        if len(recent) >= ENOUGH_CHECKS:
            found[name] = f"{round(sum(recent) / len(recent) * 100)}%"
    return found


def rank(names: list[str], broken: list[str] | None = None) -> list[str]:
    """Сначала проверенные временем, затем неизвестные, в конце ненадёжные.

    Если известно, что именно сломано, оценка берётся по этим сервисам: при сломанном YouTube
    стратегия, у которой он держится, полезнее той, что лучше в среднем.

    Порядок среди равных сохраняется: неизвестная стратегия не хуже известной плохой, но и
    выше проверенной её ставить не за что.
    """
    records = load()
    now = datetime.now()

    def weight(name: str) -> float:
        entries = _entries(name, records, now)
        if broken:
            weights = []
            for service in broken:
                seen = [service in entry.working for entry in entries
                        if service in entry.working or service in entry.broken]
                weights.append(score(sum(seen), len(seen)))
            return sum(weights) / len(weights)
        return score(sum(entry.ok for entry in entries), len(entries))

    return sorted(names, key=weight, reverse=True)


def better_choice(active: str, now: datetime | None = None) -> tuple[str, int, int]:
    """Стратегия, которая за две недели держалась заметно лучше включённой.

    Возвращает имя и обе доли в процентах. Пусто, если советовать нечего: у включённой мало
    проверок, она и так хороша, или другие проверялись слишком мало.
    """
    now = now or datetime.now()
    records = load()
    own = [entry.ok for entry in _entries(active, records, now)]
    if len(own) < ADVICE_CHECKS:
        return "", 0, 0
    own_rate = sum(own) / len(own)
    if own_rate >= ADVICE_ENOUGH:
        return "", 0, 0

    best, best_score, best_rate = "", 0.0, 0.0
    for name in records:
        if name == active or (paths.core_dir().is_dir() and not fingerprint(name)):
            # Стратегии уже нет в ядре: переключаться не на что.
            continue
        other = [entry.ok for entry in _entries(name, records, now)]
        if len(other) < ADVICE_CHECKS:
            continue
        candidate = score(sum(other), len(other))
        if candidate - own_rate >= ADVICE_GAP and candidate > best_score:
            best, best_score, best_rate = name, candidate, sum(other) / len(other)

    if not best:
        return "", 0, 0
    return best, round(best_rate * 100), round(own_rate * 100)
