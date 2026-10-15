"""Режимы IP-набора `lists/ipset-all.txt`.

Апстрим кодирует режим самим содержимым файла:

* пустой файл — `any`: обход применяется ко всем адресам;
* единственная строка `203.0.113.113/32` (адрес из документационной сети,
  который никуда не маршрутизируется) — `none`: обход по ipset выключен;
* всё остальное — `loaded`: работает скачанный список.

Переключение сохраняет реальный список в `ipset-all.txt.backup`, чтобы в режим
`loaded` можно было вернуться без повторной загрузки.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import requests

from app.core import paths

log = logging.getLogger(__name__)

Mode = Literal["any", "none", "loaded"]

NONE_MARKER = "203.0.113.113/32"
IPSET_URL = (
    "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube"
    "/refs/heads/main/.service/ipset-service.txt"
)

LABELS: dict[Mode, str] = {
    "any": "любые адреса",
    "none": "выключен",
    "loaded": "по списку",
}


def list_file() -> Path:
    return paths.core_lists() / "ipset-all.txt"


def backup_file() -> Path:
    return list_file().with_suffix(".txt.backup")


def status(path: Path | None = None) -> Mode:
    path = path or list_file()
    if not path.exists():
        return "any"
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "any"

    if not content.strip():
        return "any"
    return "none" if NONE_MARKER in content else "loaded"


def has_backup(path: Path | None = None) -> bool:
    return (path or backup_file()).exists()


def set_mode(mode: Mode) -> None:
    """Переводит ipset в нужный режим, сохраняя реальный список в бэкап."""
    target = list_file()
    backup = backup_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    current = status(target)

    if mode == current:
        return

    if current == "loaded":
        backup.unlink(missing_ok=True)
        target.replace(backup)

    if mode == "none":
        target.write_text(f"{NONE_MARKER}\n", encoding="utf-8")
    elif mode == "any":
        target.write_text("", encoding="utf-8")
    elif mode == "loaded":
        if not backup.exists():
            raise FileNotFoundError(
                "нет сохранённого списка — сначала обновите ipset через раздел «Обновления»"
            )
        target.unlink(missing_ok=True)
        backup.replace(target)


def next_mode(current: Mode) -> Mode:
    """Порядок переключения по кругу, как в меню service.bat."""
    return {"loaded": "none", "none": "any", "any": "loaded"}[current]  # type: ignore[return-value]


def update_list(timeout: int = 30) -> int:
    """Скачивает актуальный ipset из репозитория Flowseal.

    Возвращает число записей. Скачанное кладётся в бэкап и, если режим сейчас
    `loaded`, сразу становится активным списком.
    """
    response = requests.get(IPSET_URL, timeout=timeout, headers={"Cache-Control": "no-cache"})
    response.raise_for_status()
    content = response.text

    entries = [line for line in content.splitlines() if line.strip()]
    if not entries:
        raise ValueError("репозиторий вернул пустой список ipset")

    was_loaded = status() == "loaded"
    target = list_file()
    target.parent.mkdir(parents=True, exist_ok=True)

    if was_loaded:
        target.write_text(content, encoding="utf-8")
        backup_file().write_text(content, encoding="utf-8")
    else:
        backup_file().write_text(content, encoding="utf-8")

    log.info("Список ipset обновлён: %d записей", len(entries))
    return len(entries)
