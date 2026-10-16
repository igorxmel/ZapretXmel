"""Установка и откат ядра.

Схема: распаковка во временную папку → проверка → перенос пользовательских
файлов → старое ядро уезжает в бэкап → новое занимает его место. Папка `core/`
подменяется последним шагом, поэтому прерванное обновление не оставляет
полуразобранную сборку.
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core import coreinfo, lists, paths, strategies

log = logging.getLogger(__name__)

# Файлы, которые принадлежат пользователю и должны пережить обновление.
PRESERVED_PATTERNS = (
    "lists/*-user.txt",
    "lists/ipset-all.txt",
    "lists/ipset-all.txt.backup",
    "utils/game_filter.enabled",
    "utils/check_updates.enabled",
)

Progress = Callable[[str], None]


class InstallError(Exception):
    """Архив не похож на сборку zapret или установку не удалось завершить."""


@dataclass(frozen=True)
class Backup:
    path: Path
    version: str
    created_at: datetime

    @property
    def label(self) -> str:
        stamp = self.created_at.strftime("%d.%m.%Y %H:%M")
        return f"{self.version or 'без версии'} — {stamp}"


def _safe_members(archive: zipfile.ZipFile, target: Path) -> list[zipfile.ZipInfo]:
    """Отбрасывает записи, которые пытаются вылезти за пределы целевой папки."""
    members: list[zipfile.ZipInfo] = []
    target = target.resolve()
    for member in archive.infolist():
        destination = (target / member.filename).resolve()
        if not destination.is_relative_to(target):
            log.warning("Запись архива отброшена как небезопасная: %s", member.filename)
            continue
        members.append(member)
    return members


def extract(archive_path: Path, staging: Path, progress: Progress | None = None) -> Path:
    """Распаковывает архив и возвращает корень сборки внутри него."""
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    if progress:
        progress("Распаковка архива…")

    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(staging, members=_safe_members(archive, staging))

    # Релизы Flowseal упакованы с одной корневой папкой внутри архива.
    entries = [entry for entry in staging.iterdir() if entry.is_dir()]
    if len(entries) == 1 and not (staging / "bin").exists():
        return entries[0]
    return staging


def validate_bundle(root: Path) -> None:
    """Проверяет, что распакованное действительно похоже на сборку zapret."""
    if not (root / "bin" / "winws.exe").exists():
        raise InstallError("в архиве нет bin/winws.exe")
    if not (root / "bin").glob("WinDivert*"):
        raise InstallError("в архиве нет драйвера WinDivert")
    if not strategies.discover(root):
        raise InstallError("в архиве нет ни одной стратегии")


def carry_over_user_files(source: Path, target: Path, progress: Progress | None = None) -> int:
    """Переносит пользовательские файлы и добавленные вручную стратегии."""
    if not source.is_dir():
        return 0

    if progress:
        progress("Перенос пользовательских списков…")

    carried = 0
    for pattern in PRESERVED_PATTERNS:
        for item in source.glob(pattern):
            if not item.is_file():
                continue
            destination = target / item.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
            carried += 1

    # Стратегии, которых нет в новой сборке, пользователь добавил сам.
    incoming = {path.name.lower() for path in target.glob("*.bat")}
    for path in strategies.discover(source):
        if path.name.lower() not in incoming:
            shutil.copy2(path, target / path.name)
            carried += 1

    return carried


def _backup_dir_name(version: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}_{version or 'unknown'}"


def list_backups() -> list[Backup]:
    """Бэкапы ядра, новые первыми."""
    root = paths.backups_dir()
    if not root.is_dir():
        return []

    backups: list[Backup] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        stamp, _, version = entry.name.partition("_")
        try:
            created = datetime.strptime(stamp, "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        backups.append(Backup(path=entry, version=version, created_at=created))

    return sorted(backups, key=lambda backup: backup.created_at, reverse=True)


def install_core(
    archive_path: Path,
    progress: Progress | None = None,
    keep_backups: int = 3,
) -> str:
    """Ставит ядро из архива, сохраняя предыдущую версию для отката.

    Возвращает версию установленной сборки.
    """
    core = paths.core_dir()
    staging_root = paths.downloads_dir() / "staging"

    bundle = extract(archive_path, staging_root, progress)
    validate_bundle(bundle)

    new_version = coreinfo.read_version(bundle)
    carry_over_user_files(core, bundle, progress)

    if core.exists():
        if progress:
            progress("Сохранение текущей версии в бэкап…")
        backup_path = paths.backups_dir() / _backup_dir_name(coreinfo.read_version(core))
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(core), str(backup_path))

    if progress:
        progress("Установка новой версии…")
    shutil.move(str(bundle), str(core))

    if staging_root.exists():
        shutil.rmtree(staging_root, ignore_errors=True)

    # Стратегии ссылаются на пользовательские списки, а в архиве Flowseal
    # их нет: у него их создаёт первый запуск консольного меню.
    lists.ensure_user_lists()

    _prune_backups(keep_backups)
    log.info("Ядро обновлено до версии %s", new_version or "неизвестной")
    return new_version


def _prune_backups(keep: int) -> None:
    for backup in list_backups()[keep:]:
        shutil.rmtree(backup.path, ignore_errors=True)
        log.info("Удалён старый бэкап %s", backup.path.name)


def rollback(backup: Backup | None = None, progress: Progress | None = None) -> str:
    """Возвращает предыдущую версию ядра, сохранив текущие пользовательские списки."""
    target = backup or next(iter(list_backups()), None)
    if target is None:
        raise InstallError("нет ни одного бэкапа для отката")

    core = paths.core_dir()
    if progress:
        progress(f"Откат на версию {target.version or 'предыдущую'}…")

    carry_over_user_files(core, target.path, progress)

    if core.exists():
        discarded = paths.downloads_dir() / "discarded"
        shutil.rmtree(discarded, ignore_errors=True)
        shutil.move(str(core), str(discarded))

    shutil.move(str(target.path), str(core))
    shutil.rmtree(paths.downloads_dir() / "discarded", ignore_errors=True)

    log.info("Выполнен откат на версию %s", target.version)
    return target.version
