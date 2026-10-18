"""Прошлые разборы нейросетью.

Разбор — не одноразовая справка: человек спрашивает, пробует совет, снова
спрашивает. Без истории предыдущий ответ исчезает вместе с окном, и сравнить
«что советовали в прошлый раз» становится негде.

Храним рядом с настройками и в том же виде, в каком показываем: вопрос,
ответ и чем отвечали. Снимок системы не сохраняем — он велик, устаревает за
минуты и уже уехал наружу; держать его копию на диске ни к чему.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime

from app.core import paths

log = logging.getLogger(__name__)

FILE_NAME = "ai-history.json"

# Сколько разборов помнить. Больше незачем: советы устаревают вместе с
# правилами провайдера, а файл лежит рядом с настройками.
LIMIT = 20


@dataclass
class Entry:
    """Один разбор."""

    asked_at: str = ""
    problem: str = ""
    provider: str = ""
    model: str = ""
    verdict: str = ""
    cause: str = ""
    steps: list[str] = field(default_factory=list)
    confidence: str = ""

    @property
    def title(self) -> str:
        """Строка для списка: когда и о чём спрашивали."""
        when = self.asked_at[:16].replace("T", " ")
        about = self.problem.strip().splitlines()[0] if self.problem.strip() else self.verdict
        return f"{when} — {about[:60] or 'без описания'}"


def file():
    return paths.data_dir() / FILE_NAME


def load() -> list[Entry]:
    """Прошлые разборы, свежие первыми. Битый файл — просто пустая история."""
    try:
        raw = json.loads(file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(raw, list):
        return []

    entries = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        known = {key: item.get(key) for key in Entry.__dataclass_fields__ if key in item}
        try:
            entries.append(Entry(**known))
        except TypeError:
            continue
    return entries


def remember(analysis, problem: str) -> None:
    """Дописывает разбор в начало истории."""
    entry = Entry(
        asked_at=datetime.now().isoformat(timespec="seconds"),
        problem=problem,
        provider=analysis.provider,
        model=analysis.model,
        verdict=analysis.verdict,
        cause=analysis.cause,
        steps=list(analysis.steps),
        confidence=analysis.confidence,
    )

    entries = [entry, *load()][:LIMIT]
    try:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        file().write_text(
            json.dumps([asdict(item) for item in entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        log.warning("Не удалось сохранить историю разборов")


def clear() -> None:
    try:
        file().unlink(missing_ok=True)
    except OSError:
        log.warning("Не удалось очистить историю разборов")
