"""Список изменений, который читает сама программа.

Тот же `CHANGELOG.md`, из которого собирается описание релиза, едет внутрь
сборки: после обновления человек должен увидеть, что поменялось, не открывая
браузер — и без сети, которой у него может не быть именно из-за блокировок.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.core import paths
from app.core.updater import github

log = logging.getLogger(__name__)

FILENAME = "CHANGELOG.md"

_HEADING = re.compile(r"^##\s+v?(\d\S*)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Entry:
    """Раздел списка: версия и что в ней изменилось."""

    version: str
    notes: str


def file() -> Path:
    """Где лежит список изменений.

    В сборке он кладётся рядом с картинками (единственная папка с данными,
    которую забирает PyInstaller), в исходниках — в корне проекта.
    """
    packed = paths.assets_dir() / FILENAME
    return packed if packed.is_file() else paths.app_root() / FILENAME


def section(text: str, version: str) -> str:
    """Содержимое раздела `## <версия>` без заголовка.

    Для тестовой сборки (`1.1.0-rc.1`) годится раздел обычной версии:
    описывают они одно и то же, и переписывать его дважды, слово в слово,
    только ради номера — верный способ развести их по содержанию.
    """
    for wanted in _candidates(version):
        pattern = re.compile(
            rf"^##\s+v?{re.escape(wanted)}\s*$(.*?)(?=^##\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        found = pattern.search(text)
        if found:
            return found.group(1).strip()

    return ""


def _candidates(version: str) -> list[str]:
    """Номер версии и он же без пометки тестовой сборки."""
    base = version.split("-", 1)[0]
    return [version] if base == version else [version, base]


def parse(text: str) -> list[Entry]:
    """Все разделы с номером версии, в порядке следования в файле."""
    headings = list(_HEADING.finditer(text))
    found = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        found.append(Entry(heading.group(1), text[heading.end() : end].strip()))
    return found


def _text() -> str:
    try:
        return file().read_text(encoding="utf-8")
    except OSError:
        log.info("Список изменений не найден: %s", file())
        return ""


def read(version: str) -> str:
    """Раздел про версию. Пустая строка — значит рассказывать нечего."""
    return section(_text(), version)


def _from_current_down(text: str, current: str, seen: str) -> list[Entry]:
    """Текущая версия и те, что вышли после `seen`, от новых к старым.

    Текущая идёт отдельно: у тестовой сборки её раздел называется номером
    обычной версии, и сравнением номеров его не найти.
    """
    notes = section(text, current)
    top = [Entry(current, notes)] if notes else []
    older = [
        entry
        for entry in parse(text)
        if entry.notes
        and github.is_newer(current, entry.version)
        and github.is_newer(entry.version, seen)
    ]
    older.sort(key=lambda entry: github.parse_version(entry.version), reverse=True)
    return top + older


def since(seen: str, current: str) -> list[Entry]:
    """Что изменилось с версии `seen`: от `current` вниз, без самой `seen`.

    Обновляются не на каждую версию, и рассказ только о последней скрывал всё
    вышедшее между ними. Без отметки о просмотре рассказываем только о текущей:
    откуда считать, неизвестно, а вся история не про это обновление.
    """
    text = _text()
    if not seen:
        notes = section(text, current)
        return [Entry(current, notes)] if notes else []
    return _from_current_down(text, current, seen)


def history(current: str) -> list[Entry]:
    """Вся история до текущей версии, от новых к старым."""
    return _from_current_down(_text(), current, "")
