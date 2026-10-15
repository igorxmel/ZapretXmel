"""Ярлык на рабочем столе.

Программа портативная: это один файл, который человек кладёт куда захочет, и
найти его потом бывает негде — в меню «Пуск» её нет, потому что установщика
нет тоже. Ярлык эту дыру закрывает.

Сам `.lnk` — это COM-объект оболочки Windows, и собирать его из Python без
сторонних библиотек проще всего через PowerShell: там он создаётся тремя
строками, а `pywin32` ради этого тянуть не хочется.

Путь к рабочему столу спрашиваем у системы, а не склеиваем из профиля:
папка переносится в OneDrive и на локализованных системах называется
по-своему.
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
from ctypes import wintypes
from pathlib import Path

from app.core import paths

log = logging.getLogger(__name__)

NAME = "ZapretXmel"
CREATE_NO_WINDOW = 0x08000000

# FOLDERID_Desktop — идентификатор рабочего стола в известных папках Windows.
_DESKTOP_GUID = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


def desktop_dir() -> Path:
    """Папка рабочего стола по мнению самой Windows."""
    try:
        guid = _GUID()
        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32

        if ole32.CLSIDFromString(_DESKTOP_GUID, ctypes.byref(guid)) != 0:
            raise OSError("не удалось разобрать идентификатор папки")

        buffer = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(buffer)) != 0:
            raise OSError("система не вернула путь к рабочему столу")

        try:
            return Path(buffer.value or "")
        finally:
            ole32.CoTaskMemFree(buffer)
    except (AttributeError, OSError):
        log.debug("Не удалось спросить путь к рабочему столу, беру из профиля")
        return Path.home() / "Desktop"


def path() -> Path:
    return desktop_dir() / f"{NAME}.lnk"


def exists() -> bool:
    return path().is_file()


def target() -> Path:
    """Файл, на который должен указывать ярлык."""
    return paths.executable()


def create(executable: Path | None = None) -> bool:
    """Создаёт или обновляет ярлык. False — не получилось."""
    destination = path()
    points_to = executable or target()

    script = (
        "$link = (New-Object -ComObject WScript.Shell).CreateShortcut("
        f"'{destination}');"
        f"$link.TargetPath = '{points_to}';"
        f"$link.WorkingDirectory = '{points_to.parent}';"
        f"$link.IconLocation = '{points_to},0';"
        f"$link.Description = 'ZapretXmel — обход блокировок';"
        "$link.Save()"
    )

    try:
        completed = subprocess.run(  # noqa: S603 — фиксированная системная утилита
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.exception("Не удалось создать ярлык")
        return False

    if completed.returncode != 0:
        log.warning("PowerShell не создал ярлык: код %s", completed.returncode)
        return False

    log.info("Ярлык на рабочем столе указывает на %s", points_to)
    return True


def remove() -> bool:
    try:
        path().unlink(missing_ok=True)
        return True
    except OSError:
        log.warning("Не удалось удалить ярлык")
        return False


def retarget(executable: Path) -> None:
    """Переписывает ярлык после переезда программы.

    Если ярлыка нет, создавать его не надо: человек его не просил.
    """
    if exists():
        create(executable)
