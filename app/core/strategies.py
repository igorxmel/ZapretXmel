"""Каталог стратегий: сканирует папку ядра и разбирает найденные .bat.

Список строится из того, что лежит на диске, поэтому новые стратегии из
очередного релиза Flowseal появляются в интерфейсе сами, без правок кода.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core import gamefilter, paths
from app.core.batfile import BatParseError, StrategySpec, parse_bat

log = logging.getLogger(__name__)

# Служебные .bat сборки — это не стратегии.
_SERVICE_PREFIXES = ("service", "check_updates")


def is_strategy_file(path: Path) -> bool:
    return path.suffix.lower() == ".bat" and not path.name.lower().startswith(_SERVICE_PREFIXES)


def discover(root: Path | None = None) -> list[Path]:
    """Возвращает файлы стратегий в порядке, привычном по меню service.bat."""
    root = root or paths.core_dir()
    if not root.is_dir():
        return []
    return sorted((p for p in root.glob("*.bat") if is_strategy_file(p)), key=_natural_key)


def _natural_key(path: Path) -> str:
    """Ключ сортировки, повторяющий порядок меню `service.bat`.

    Апстрим дополняет числа нулями до восьми знаков и сравнивает как строки.
    Благодаря этому ALT2 оказывается перед ALT10, а «general (ALT)» — перед
    «general (ALT2)», потому что закрывающая скобка по коду меньше цифры.
    """
    import re

    return re.sub(r"\d+", lambda match: match.group().rjust(8, "0"), path.stem.lower())


def load_all(root: Path | None = None) -> list[StrategySpec]:
    """Разбирает все стратегии; нечитаемые пропускаются с записью в лог."""
    root = root or paths.core_dir()
    game_filter = gamefilter.load()
    specs: list[StrategySpec] = []

    for path in discover(root):
        try:
            specs.append(
                parse_bat(
                    path,
                    root=root,
                    game_filter_tcp=game_filter.tcp_value,
                    game_filter_udp=game_filter.udp_value,
                )
            )
        except (BatParseError, OSError) as error:
            log.warning("Стратегия %s пропущена: %s", path.name, error)

    return specs


def load_one(name: str, root: Path | None = None) -> StrategySpec | None:
    """Разбирает одну стратегию по имени файла без расширения."""
    root = root or paths.core_dir()
    path = root / f"{name}.bat"
    if not path.exists():
        return None

    game_filter = gamefilter.load()
    try:
        return parse_bat(
            path,
            root=root,
            game_filter_tcp=game_filter.tcp_value,
            game_filter_udp=game_filter.udp_value,
        )
    except (BatParseError, OSError) as error:
        log.warning("Стратегия %s не разобрана: %s", path.name, error)
        return None
