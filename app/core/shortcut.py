"""Ярлыки: на рабочем столе и в меню «Пуск».

Программа портативная: это один файл, который человек кладёт куда захочет, и
найти его потом бывает негде — установщика нет, поэтому сама она никуда не
прописывается. Ярлыки эту дыру закрывают.

Мест два, потому что ищут по-разному. Рабочий стол — чтобы запускать
мышкой. Меню «Пуск» — чтобы программа **находилась поиском Windows**: он
индексирует папку `Programs`, и ярлык в ней превращает «Пуск → zapret» в
рабочий способ запуска.

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
import os
import subprocess
from ctypes import wintypes
from pathlib import Path

from app.core import paths

log = logging.getLogger(__name__)

NAME = "ZapretXmel"
CREATE_NO_WINDOW = 0x08000000

DESKTOP = "desktop"
START_MENU = "start_menu"

# Идентификаторы известных папок Windows: FOLDERID_Desktop и FOLDERID_Programs.
# Programs — это та самая папка, которую просматривает поиск в «Пуске».
_FOLDERS = {
    DESKTOP: "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    START_MENU: "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}",
}

TITLES = {
    DESKTOP: "ярлык на рабочем столе",
    START_MENU: "ярлык в меню «Пуск»",
}


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


def folder(where: str = DESKTOP) -> Path:
    """Папка ярлыка по мнению самой Windows.

    Спрашиваем систему, а не склеиваем из профиля: рабочий стол переносится
    в OneDrive, а на локализованных системах обе папки называются по-своему.
    """
    try:
        guid = _GUID()
        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32

        if ole32.CLSIDFromString(_FOLDERS[where], ctypes.byref(guid)) != 0:
            raise OSError("не удалось разобрать идентификатор папки")

        buffer = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(buffer)) != 0:
            raise OSError("система не вернула путь к папке")

        try:
            return Path(buffer.value or "")
        finally:
            ole32.CoTaskMemFree(buffer)
    except (AttributeError, OSError):
        log.debug("Не удалось спросить путь к папке %s, беру из профиля", where)
        return _fallback(where)


def _fallback(where: str) -> Path:
    if where == START_MENU:
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / (
            "Start Menu"
        ) / "Programs"
    return Path.home() / "Desktop"


def desktop_dir() -> Path:
    return folder(DESKTOP)


def path(where: str = DESKTOP) -> Path:
    return folder(where) / f"{NAME}.lnk"


def exists(where: str = DESKTOP) -> bool:
    return path(where).is_file()


def target() -> Path:
    """Файл, на который должен указывать ярлык."""
    return paths.executable()


def create(executable: Path | None = None, where: str = DESKTOP) -> bool:
    """Создаёт или обновляет ярлык. False — не получилось."""
    destination = path(where)
    points_to = executable or target()

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.warning("Не удалось создать папку %s", destination.parent)
        return False

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

    log.info("%s указывает на %s", TITLES[where].capitalize(), points_to)
    return True


def remove(where: str = DESKTOP) -> bool:
    try:
        path(where).unlink(missing_ok=True)
        return True
    except OSError:
        log.warning("Не удалось удалить %s", TITLES[where])
        return False


def remove_all() -> list[str]:
    """Убирает оба ярлыка. Возвращает названия тех, что были."""
    removed = []
    for where in _FOLDERS:
        if exists(where) and remove(where):
            removed.append(TITLES[where])
    return removed


def retarget(executable: Path) -> None:
    """Переписывает ярлыки после переезда программы.

    Отсутствующий ярлык не создаём: человек его не просил.
    """
    for where in _FOLDERS:
        if exists(where):
            create(executable, where)
