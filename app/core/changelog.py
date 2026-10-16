"""Список изменений, который читает сама программа.

Тот же `CHANGELOG.md`, из которого собирается описание релиза, едет внутрь
сборки: после обновления человек должен увидеть, что поменялось, не открывая
браузер — и без сети, которой у него может не быть именно из-за блокировок.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core import paths

log = logging.getLogger(__name__)

FILENAME = "CHANGELOG.md"


def file() -> Path:
    """Где лежит список изменений.

    В сборке он кладётся рядом с картинками (единственная папка с данными,
    которую забирает PyInstaller), в исходниках — в корне проекта.
    """
    packed = paths.assets_dir() / FILENAME
    return packed if packed.is_file() else paths.app_root() / FILENAME


def section(text: str, version: str) -> str:
    """Содержимое раздела `## <версия>` без заголовка."""
    pattern = re.compile(
        rf"^##\s+v?{re.escape(version)}\s*$(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    found = pattern.search(text)
    return found.group(1).strip() if found else ""


def read(version: str) -> str:
    """Раздел про версию. Пустая строка — значит рассказывать нечего."""
    try:
        text = file().read_text(encoding="utf-8")
    except OSError:
        log.info("Список изменений не найден: %s", file())
        return ""

    return section(text, version)
