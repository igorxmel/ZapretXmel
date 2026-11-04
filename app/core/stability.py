"""Журнал стабильности стратегий.

Подбор отвечает на вопрос «что работает сейчас», а человеку важно ещё «что не отвалится
через час». Сторож и так регулярно проверяет обход, поэтому результаты достаточно
запоминать. Журнал лежит только на этом компьютере и никуда не отправляется.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime

from app.core import paths

log = logging.getLogger(__name__)

FILENAME = "stability.json"
# Меньше этого о стратегии ещё ничего не известно: две удачные проверки подряд не лучше ста.
ENOUGH_CHECKS = 5


@dataclass
class Record:
    checks: int = 0
    passed: int = 0
    # С какого момента стратегия работает без сбоев. Пусто — сейчас она не работает.
    working_since: str = ""

    @property
    def rate(self) -> float:
        return self.passed / self.checks if self.checks else 0.0


def _file():
    return paths.data_dir() / FILENAME


def load() -> dict[str, Record]:
    """Журнал целиком. Испорченный файл — не повод ломать опрос."""
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
        return {name: Record(**values) for name, values in raw.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError, AttributeError):
        log.warning("Журнал стабильности не прочитан, начинаю заново")
        return {}


def _save(records: dict[str, Record]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    data = {name: asdict(record) for name, record in records.items()}
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, path)


def record(strategy: str, works: bool, now: datetime | None = None) -> None:
    """Запоминает одну проверку работающей стратегии."""
    if not strategy:
        return

    moment = (now or datetime.now()).isoformat(timespec="seconds")
    records = load()
    item = records.setdefault(strategy, Record())
    item.checks += 1
    if works:
        item.passed += 1
        item.working_since = item.working_since or moment
    else:
        item.working_since = ""

    try:
        _save(records)
    except OSError:
        log.info("Журнал стабильности не записан", exc_info=True)


def describe(strategy: str, now: datetime | None = None) -> str:
    """Подпись для экрана стратегий."""
    item = load().get(strategy)
    if item is None or item.checks == 0:
        return "пока не проверялась"

    text = f"прошла {item.passed} из {item.checks} проверок"
    if item.working_since:
        since = datetime.fromisoformat(item.working_since)
        hours = int(((now or datetime.now()) - since).total_seconds() // 3600)
        if hours >= 48:
            text += f", без сбоев {hours // 24} дн."
        elif hours >= 1:
            text += f", без сбоев {hours} ч."
    return text


def rank(names: list[str]) -> list[str]:
    """Сначала проверенные временем, затем неизвестные, в конце ненадёжные.

    Порядок среди равных сохраняется: неизвестная стратегия не хуже известной плохой, но и
    выше проверенной её ставить не за что.
    """
    records = load()

    def weight(name: str) -> float:
        item = records.get(name)
        if item is None or item.checks < ENOUGH_CHECKS:
            return 0.5
        return item.rate

    return sorted(names, key=weight, reverse=True)
