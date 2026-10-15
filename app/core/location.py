"""Смена места установки.

Ядро zapret весит под сотню мегабайт, и держать его там, откуда запустили
.exe (а это чаще всего «Загрузки»), хочется не всем. Здесь — проверка
выбранной папки и перенос в неё уже установленного.

Переносится всё изменяемое состояние: ядро, настройки с логами и сайдкар
Telegram. Сам исполняемый файл остаётся на месте — он один и переживает
обновление себя через переименование, которому переезд только помешал бы.

Служба zapret хранит абсолютный путь к winws.exe, поэтому после переноса её
обязательно переустанавливают заново. За это отвечает вызывающая сторона —
`Controller.relocate`.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app.core import paths

log = logging.getLogger(__name__)

# Папки, которые составляют установку. Имена совпадают с теми, что отдаёт
# `paths`, — переносим их целиком, не разбирая содержимое.
MOVABLE: tuple[str, ...] = ("core", "data", "tgproxy")


@dataclass
class Relocation:
    """Итог переезда: что перенесли, а что уже лежало на новом месте."""

    target: Path
    moved: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = []
        if self.moved:
            parts.append("перенесено: " + ", ".join(self.moved))
        if self.kept:
            parts.append("уже было на месте: " + ", ".join(self.kept))
        return "; ".join(parts) or "переносить было нечего"


def check_target(path: Path) -> str:
    """Причина, по которой папка не подходит. Пустая строка — подходит.

    Проверяется то, что сделает переезд невозможным или бессмысленным.
    Кириллица в пути и OneDrive не запрещены здесь: о них предупреждает
    диагностика, и запрещать выбор из-за предупреждения было бы грубо.
    """
    try:
        target = Path(path).expanduser()
    except (OSError, ValueError):
        return "Такой путь система не принимает."

    if not str(target).strip():
        return "Папка не выбрана."
    if not target.is_absolute():
        return "Нужен полный путь, например D:\\ZapretXmel."
    if not Path(target.anchor).exists():
        return f"Диска {target.anchor} нет в системе."
    if target.exists() and not target.is_dir():
        return "По этому пути лежит файл, а не папка."

    current = paths.install_root().resolve()
    try:
        resolved = target.resolve()
    except OSError:
        return "Такой путь система не принимает."

    if resolved == current:
        return "Это и есть текущее место установки."
    if resolved.is_relative_to(current) and _has_installed_parts(current):
        return "Нельзя переносить установку внутрь себя же."
    if current.is_relative_to(resolved):
        return "Эта папка уже содержит установку — выберите другую."

    return _writable(resolved)


def _writable(target: Path) -> str:
    """Пробует создать папку и записать в неё: прав может не быть."""
    probe = target / ".zapretxmel-write-test"
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe.touch()
    except OSError:
        return "В эту папку нельзя записывать — выберите другую или запустите от администратора."
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            log.debug("Не удалось убрать пробный файл в %s", target)

    return ""


def _has_installed_parts(root: Path) -> bool:
    return any((root / name).exists() for name in MOVABLE)


def free_space_mb(path: Path) -> int:
    """Свободное место на диске выбранной папки — чтобы показать его до переезда."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free // (1024 * 1024)
    except OSError:
        return 0


def installed_size_mb() -> int:
    """Размер того, что придётся перенести."""
    total = 0
    root = paths.install_root()
    for name in MOVABLE:
        folder = root / name
        if not folder.is_dir():
            continue
        for current, _, files in os.walk(folder):
            for file in files:
                try:
                    total += (Path(current) / file).stat().st_size
                except OSError:
                    continue
    return total // (1024 * 1024)


def relocate(target: Path) -> Relocation:
    """Переносит установку в `target` и запоминает новое место.

    Если в новой папке такая часть уже есть, она остаётся нетронутой, а старая
    не удаляется: молча перетирать чужое ядро или чужие настройки нельзя, а
    решать, какие из двух нужнее, — не дело программы.

    Указатель переписывается только после переноса. Иначе сбой на середине
    оставил бы программу смотреть в полупустую папку.
    """
    reason = check_target(target)
    if reason:
        raise ValueError(reason)

    source = paths.install_root().resolve()
    destination = Path(target).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    result = Relocation(target=destination)
    for name in MOVABLE:
        origin = source / name
        if not origin.exists():
            continue
        if (destination / name).exists():
            result.kept.append(name)
            continue
        shutil.move(str(origin), str(destination / name))
        result.moved.append(name)
        log.info("Перенесено %s → %s", origin, destination / name)

    # Портативный режим обозначается отсутствием указателя — так папку с
    # программой можно перенести куда угодно, и она останется работоспособной.
    paths.set_install_root(None if destination == paths.app_root() else destination)
    paths.ensure_dirs()
    return result
