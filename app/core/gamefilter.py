"""Игровой фильтр — диапазоны портов, которые стратегия обрабатывает дополнительно.

Состояние лежит в `core/utils/game_filter.enabled` в том же формате, который
читает и пишет `service.bat`, так что консольное меню и GUI видят одно и то же.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core import paths
from app.core.batfile import GAME_FILTER_OFF

Mode = Literal["disabled", "all", "tcp", "udp"]

DEFAULT_RANGE = "1024-65535"
_ITEM_RE = re.compile(r"^[1-9][0-9]{0,4}(-[1-9][0-9]{0,4})?$")


@dataclass(frozen=True)
class GameFilter:
    mode: Mode = "disabled"
    tcp_range: str = DEFAULT_RANGE
    udp_range: str = DEFAULT_RANGE

    @property
    def tcp_value(self) -> str:
        """Чем заменить `%GameFilterTCP%` в стратегии."""
        return self.tcp_range if self.mode in ("all", "tcp") else GAME_FILTER_OFF

    @property
    def udp_value(self) -> str:
        return self.udp_range if self.mode in ("all", "udp") else GAME_FILTER_OFF

    @property
    def label(self) -> str:
        return {
            "disabled": "выключен",
            "all": "включён (TCP и UDP)",
            "tcp": "включён (TCP)",
            "udp": "включён (UDP)",
        }[self.mode]


def flag_file() -> Path:
    return paths.core_utils() / "game_filter.enabled"


def validate_range(value: str) -> str | None:
    """Проверяет строку диапазонов портов по правилам апстрима.

    Возвращает нормализованную строку или None, если ввод некорректен.
    Формат: элементы через запятую, каждый — `порт` или `начало-конец`.
    """
    cleaned = value.replace(" ", "")
    if not cleaned:
        return None

    for item in cleaned.split(","):
        if not _ITEM_RE.match(item):
            return None
        start, _, end = item.partition("-")
        start_num = int(start)
        end_num = int(end) if end else start_num
        if start_num > 65535 or end_num > 65535 or start_num > end_num:
            return None
    return cleaned


def load(path: Path | None = None) -> GameFilter:
    path = path or flag_file()
    if not path.exists():
        return GameFilter()

    mode: Mode = "disabled"
    tcp, udp = DEFAULT_RANGE, DEFAULT_RANGE
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return GameFilter()

    for line in content.splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip().lower(), value.strip()
        if key == "mode" and value in ("disabled", "all", "tcp", "udp"):
            mode = value  # type: ignore[assignment]
        elif key == "all":
            mode = "all"
        elif key == "tcp":
            if not value:
                mode = "tcp"
            elif validated := validate_range(value):
                tcp = validated
        elif key == "udp":
            if not value:
                mode = "udp"
            elif validated := validate_range(value):
                udp = validated

    return GameFilter(mode=mode, tcp_range=tcp, udp_range=udp)


def save(game_filter: GameFilter, path: Path | None = None) -> None:
    """Пишет состояние фильтра; при выключенном — убирает файл-флаг."""
    path = path or flag_file()
    if game_filter.mode == "disabled":
        path.unlink(missing_ok=True)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"mode={game_filter.mode}\ntcp={game_filter.tcp_range}\nudp={game_filter.udp_range}\n",
        encoding="utf-8",
    )
