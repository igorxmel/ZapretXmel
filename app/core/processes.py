"""Дешёвый перебор процессов по именам.

Опрос состояния идёт каждые несколько секунд и каждый раз ищет winws, прокси
Telegram и следы чужого zapret. Через `psutil.process_iter(["name"])` один такой
проход стоил больше сотни миллисекунд процессорного времени: psutil узнаёт имя
каждого процесса отдельным обращением, а для недоступных системных ещё и
перечитывает весь список. Три прохода за опрос на слабом ноутбуке — заметная
доля ядра, отнятая у всего остального, в том числе у прокси.

Снимок Toolhelp отдаёт имена всех процессов одним вызовом — на порядок дешевле.
Путь к файлу, который нужен для сверки «наш или чужой», спрашиваем потом только
у тех немногих процессов, чьё имя совпало.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

import psutil

log = logging.getLogger(__name__)

_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE = wintypes.HANDLE(-1).value


class _Entry(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 — так ctypes описывает структуры
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _snapshot() -> list[tuple[int, str]] | None:
    """(pid, имя) всех процессов; None — снимок не удался."""
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        return None

    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not handle or handle == _INVALID_HANDLE:
        return None

    found: list[tuple[int, str]] = []
    entry = _Entry()
    entry.dwSize = ctypes.sizeof(_Entry)
    try:
        more = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while more:
            found.append((entry.th32ProcessID, entry.szExeFile))
            more = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    return found


def _fallback() -> list[tuple[int, str]]:
    found = []
    for process in psutil.process_iter(["name"]):
        try:
            found.append((process.pid, process.info["name"] or ""))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def all_names() -> list[tuple[int, str]]:
    """(pid, имя файла) всех запущенных процессов."""
    snapshot = _snapshot()
    if snapshot is None:
        log.debug("Снимок процессов не удался, перебираю через psutil")
        return _fallback()
    return snapshot


def pids_named(*names: str) -> list[int]:
    """Номера процессов с одним из имён (без учёта регистра)."""
    wanted = {name.lower() for name in names}
    return [pid for pid, name in all_names() if name.lower() in wanted]


def executable(pid: int) -> str:
    """Путь к файлу процесса; пусто, если процесс исчез или закрыт от нас."""
    try:
        return psutil.Process(pid).exe()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return ""
