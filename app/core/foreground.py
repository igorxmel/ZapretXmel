"""Вывод окна на передний план.

Windows не даёт процессу поднимать свои окна поверх чужих, если активное окно
принадлежит не ему. После перезапуска через UAC мы оказываемся именно в таком
положении: процесс новый, активное окно осталось за тем, с чем человек работал,
и `SetForegroundWindow` молча ничего не делает — окно открывается где-то сзади,
а на панели задач только мигает кнопка.

Обход известный и дешёвый: на мгновение сделать окно «поверх всех» и тут же
снять этот признак. Системе этого достаточно, чтобы поднять окно, а для
пользователя оно не остаётся висеть над остальными.

Модуль ничего не знает о Qt: им пользуются и интерфейс, и защита от второго
запуска, которой окно видно только как дескриптор.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)

SW_RESTORE = 9

_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010

_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2


def force(hwnd: int) -> bool:
    """Разворачивает окно и выводит его вперёд. False — не получилось."""
    if not hwnd:
        return False

    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]

        window = wintypes.HWND(hwnd)
        user32.ShowWindow(window, SW_RESTORE)

        flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
        for position in (_HWND_TOPMOST, _HWND_NOTOPMOST):
            user32.SetWindowPos(window, wintypes.HWND(position), 0, 0, 0, 0, flags)

        return bool(user32.SetForegroundWindow(window))
    except (AttributeError, OSError):
        log.debug("Не удалось вывести окно на передний план")
        return False


def find(title: str) -> int:
    """Дескриптор окна с таким заголовком. 0 — такого окна нет."""
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        return int(user32.FindWindowW(None, title) or 0)
    except (AttributeError, OSError):
        return 0
