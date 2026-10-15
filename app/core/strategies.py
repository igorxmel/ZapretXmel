"""Каталог стратегий: сканирует папку ядра и разбирает найденные .bat.

Список строится из того, что лежит на диске, поэтому новые стратегии из
очередного релиза Flowseal появляются в интерфейсе сами, без правок кода.
"""

from __future__ import annotations

import logging
import shutil
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


# --- свои стратегии -----------------------------------------------------

# Пометка в имени файла. Нужна не программе, а человеку: в списке рядом со
# штатными «general (ALT7)» сразу видно, какие стратегии он завёл сам.
OWN_MARK = "своя"


def own_name(base: str) -> str:
    """Свободное имя для своей стратегии, не затирающее существующую."""
    stem = base.removesuffix(".bat").strip() or "general"
    candidate = f"{stem} ({OWN_MARK})"

    taken = {path.stem.lower() for path in discover()}
    if candidate.lower() not in taken:
        return candidate

    number = 2
    while f"{candidate}{number}".lower() in taken:
        number += 1
    return f"{candidate}{number}"


def is_own(name: str) -> bool:
    return f"({OWN_MARK}" in name


def add(source: Path) -> Path:
    """Кладёт чужой .bat в папку ядра, проверив, что он вообще стратегия.

    Разбираем до копирования: файл, который не удаётся прочитать, появился
    бы в списке и сломался только при запуске обхода — то есть тогда, когда
    причину уже не связать с добавлением.
    """
    if not paths.core_dir().is_dir():
        raise ValueError("ядро не установлено — складывать стратегию некуда")

    try:
        spec = parse_bat(source)
    except BatParseError as error:
        raise ValueError(f"файл не похож на стратегию: {error}") from error

    if not spec.argv:
        raise ValueError("в файле нет ни одной команды winws — это не стратегия")

    target = paths.core_dir() / f"{own_name(source.stem)}.bat"
    shutil.copy2(source, target)
    log.info("Добавлена своя стратегия %s", target.name)
    return target


def duplicate(name: str) -> Path:
    """Делает копию стратегии под своим именем — чтобы править, не ломая её.

    Писать стратегию с нуля почти никто не станет: у рабочих сборок слишком
    много тонкостей. А вот поправить готовую — обычное дело.
    """
    source = paths.core_dir() / f"{name}.bat"
    if not source.is_file():
        raise ValueError(f"стратегии «{name}» нет в папке ядра")

    target = paths.core_dir() / f"{own_name(name)}.bat"
    shutil.copy2(source, target)
    log.info("Создана копия стратегии: %s", target.name)
    return target
