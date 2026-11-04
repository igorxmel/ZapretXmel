"""Перенос настроек на другой компьютер.

В архив попадает только то, что человек сделал сам: настройки, свои списки, цели, профили,
свои и собранные стратегии. Ядро скачивается заново, а ключи нейросети не переносятся: они
хранятся в DPAPI, привязаны к этой учётной записи и в чужих руках были бы утечкой.

Импортировать чужой архив опасно: стратегии запускаются с правами администратора. Поэтому
имена в архиве сверяются с белым списком, и записать файл вне своих папок нельзя.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import dataclass, field, fields
from pathlib import Path

from app import __version__
from app.core import appprofile, merge, paths, strategies
from app.core.batfile import BatParseError, parse_bat
from app.core.config import Settings
from app.core.probe.services import USER_TARGETS_NAME

log = logging.getLogger(__name__)

MANIFEST = "zapretxmel-backup.json"
SETTINGS = "settings.json"
FORMAT = 1
MAX_MEMBER_BYTES = 5 * 1024 * 1024

# То, что принадлежит этому компьютеру или этому запуску, и переносить незачем.
LOCAL_SETTINGS = {"first_run_done", "last_seen_version", "selected_strategy"}

_SAFE_NAME = re.compile(r"[^\\/:*?\"<>|]+")


class BackupError(Exception):
    """Архив не удалось прочитать или он не похож на наш."""


@dataclass
class ImportResult:
    restored: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _is_portable_strategy(name: str) -> bool:
    return strategies.is_own(name) or merge.is_merged(name)


def _user_files() -> list[tuple[str, Path]]:
    """Что положить в архив: имя внутри него и файл на диске."""
    found: list[tuple[str, Path]] = []
    for path in sorted(paths.core_lists().glob("*-user.txt")):
        found.append((f"lists/{path.name}", path))

    targets = paths.core_utils() / USER_TARGETS_NAME
    if targets.is_file():
        found.append((f"utils/{targets.name}", targets))

    for path in sorted(appprofile.profiles_dir().glob(f"*{appprofile.PROFILE_SUFFIX}")):
        found.append((f"profiles/{path.name}", path))

    for path in strategies.discover():
        if _is_portable_strategy(path.stem):
            found.append((f"strategies/{path.name}", path))
    return found


def export(target: Path, settings: Settings) -> int:
    """Пишет архив. Возвращает число файлов в нём."""
    data = {
        item.name: getattr(settings, item.name)
        for item in fields(Settings)
        if item.name not in LOCAL_SETTINGS and item.name != "ai"
    }
    files = _user_files()
    manifest = {"format": FORMAT, "version": __version__, "core": str(paths.core_dir())}

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
        archive.writestr(SETTINGS, json.dumps(data, ensure_ascii=False, indent=1))
        for name, path in files:
            archive.write(path, name)

    log.info("Настройки выгружены: %s", target.name)
    return len(files)


def _destination(name: str) -> Path | None:
    """Куда можно положить файл из архива. Всё незнакомое — None."""
    folder, _, filename = name.partition("/")
    if not filename or not _SAFE_NAME.fullmatch(filename) or filename in {".", ".."}:
        return None

    if folder == "lists" and filename.endswith("-user.txt"):
        return paths.core_lists() / filename
    if folder == "utils" and filename == USER_TARGETS_NAME:
        return paths.core_utils() / filename
    if folder == "profiles" and filename.endswith(appprofile.PROFILE_SUFFIX):
        return appprofile.profiles_dir() / filename
    is_strategy = folder == "strategies" and filename.endswith(".bat")
    if is_strategy and _is_portable_strategy(filename.removesuffix(".bat")):
        return paths.core_dir() / filename
    return None


def _restore_strategy(data: bytes, target: Path, old_core: str) -> None:
    """Пути в стратегии абсолютные, поэтому на новом месте их надо поправить.

    Сначала разбираем копию: файл, который не читается, появился бы в списке и сломался
    только при включении обхода.
    """
    text = data.decode("utf-8", errors="replace")
    if old_core:
        text = text.replace(old_core, str(paths.core_dir()))

    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="")
    try:
        parse_bat(temporary, root=paths.core_dir())
        temporary.replace(target)
    except (BatParseError, OSError):
        temporary.unlink(missing_ok=True)
        raise


def _apply_settings(raw: dict, settings: Settings) -> None:
    imported = Settings.from_dict({k: v for k, v in raw.items() if k not in LOCAL_SETTINGS})
    for item in fields(Settings):
        if item.name not in LOCAL_SETTINGS and item.name != "ai" and item.name in raw:
            setattr(settings, item.name, getattr(imported, item.name))
    settings.save()


def restore(source: Path, settings: Settings) -> ImportResult:
    """Читает архив. Файлы перезаписываются, остальное на компьютере не трогается."""
    result = ImportResult()
    try:
        with zipfile.ZipFile(source) as archive:
            if MANIFEST not in archive.namelist():
                raise BackupError("это не архив настроек ZapretXmel")
            manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
            if manifest.get("format") != FORMAT:
                raise BackupError("архив сделан другой версией программы")

            for info in archive.infolist():
                if info.filename in {MANIFEST, SETTINGS} or info.is_dir():
                    continue
                target = _destination(info.filename)
                if target is None or info.file_size > MAX_MEMBER_BYTES:
                    result.skipped.append(info.filename)
                    continue
                if not target.parent.is_dir() and target.parent != appprofile.profiles_dir():
                    # Нет ядра: положить свои списки и стратегии пока некуда.
                    result.skipped.append(info.filename)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(info)
                try:
                    if target.suffix == ".bat":
                        _restore_strategy(data, target, str(manifest.get("core", "")))
                    else:
                        target.write_bytes(data)
                    result.restored.append(info.filename)
                except (BatParseError, OSError):
                    log.warning("Файл из архива не восстановлен: %s", info.filename)
                    result.skipped.append(info.filename)

            if SETTINGS in archive.namelist():
                raw = json.loads(archive.read(SETTINGS).decode("utf-8"))
                _apply_settings(raw, settings)
                result.restored.append(SETTINGS)
    except (zipfile.BadZipFile, ValueError, AttributeError, OSError) as error:
        raise BackupError(f"архив не прочитан: {error}") from error

    log.info("Настройки загружены: %d файлов", len(result.restored))
    return result
