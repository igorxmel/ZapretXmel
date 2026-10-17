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


def read(version: str) -> str:
    """Раздел про версию. Пустая строка — значит рассказывать нечего."""
    try:
        text = file().read_text(encoding="utf-8")
    except OSError:
        log.info("Список изменений не найден: %s", file())
        return ""

    return section(text, version)
