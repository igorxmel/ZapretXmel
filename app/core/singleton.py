"""Защита от второго запуска.

Два окна и два значка в трее — это не просто неопрятно: оба экземпляра начнут
управлять одной службой и одними файлами настроек, и чьи изменения уцелеют,
предсказать нельзя.

Поэтому первый запуск занимает именованный мьютекс, а второй, обнаружив его,
поднимает уже открытое окно и тихо выходит. Мьютекс освобождается системой при
завершении процесса — даже если тот упал, так что «залипнуть» он не может.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import sys
from ctypes import wintypes
from pathlib import Path

import psutil

from app.core import foreground

log = logging.getLogger(__name__)

# Имя уникально для приложения. Префикс Local\ ограничивает его текущим
# сеансом: на сервере терминалов у каждого пользователя будет своя копия.
MUTEX_NAME = "Local\\ZapretXmel.SingleInstance"

_ERROR_ALREADY_EXISTS = 183

# Мьютекс держится в переменной модуля намеренно: если дать сборщику мусора
# закрыть его, защита исчезнет посреди работы программы.
_handle: int | None = None


def acquire() -> bool:
    """Занимает мьютекс. False означает, что программа уже запущена."""
    global _handle

    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]

        # Дескриптор от неудачной попытки нужно закрыть: пока он у нас,
        # объект ядра жив, и повторная проверка — после того как зависший
        # экземпляр сняли — снова увидела бы занятое имя.
        if _handle:
            kernel32.CloseHandle(_handle)
            _handle = None

        _handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if not _handle:
            return True  # не смогли проверить — пускаем, это меньшее зло

        return kernel32.GetLastError() != _ERROR_ALREADY_EXISTS
    except (AttributeError, OSError):
        log.debug("Проверка повторного запуска недоступна")
        return True


def other_instances() -> list[int]:
    """Процессы той же программы, кроме текущего.

    Только для собранной версии: в исходниках программа работает внутри
    `pythonw.exe`, и по его пути от неё не отличить ни одного чужого скрипта —
    снимать такие процессы вслепую нельзя.
    """
    if not getattr(sys, "frozen", False):
        return []

    own = Path(sys.executable).resolve()
    found: list[int] = []
    for process in psutil.process_iter(["pid", "exe"]):
        try:
            if process.pid == os.getpid():
                continue
            executable = process.info["exe"]
            if executable and Path(executable).resolve() == own:
                found.append(process.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue

    return found


def terminate_others(timeout: float = 5.0) -> int:
    """Снимает зависшие экземпляры. Возвращает число завершённых."""
    processes = []
    for pid in other_instances():
        try:
            processes.append(psutil.Process(pid))
        except psutil.NoSuchProcess:
            continue

    for process in processes:
        with contextlib.suppress(psutil.Error):
            process.terminate()

    gone, alive = psutil.wait_procs(processes, timeout=timeout)
    for process in alive:
        with contextlib.suppress(psutil.Error):
            process.kill()

    log.info("Завершено зависших экземпляров: %s", len(gone) + len(alive))
    return len(gone) + len(alive)


def focus_existing(title: str = "ZapretXmel") -> bool:
    """Поднимает окно уже запущенного экземпляра.

    Окно ищется по заголовку: свой заголовок мы задаём сами и знаем точно.
    Свёрнутый в трей экземпляр окно сохраняет — просто скрытым, и найти его
    по заголовку по-прежнему можно. False означает, что окна нет вовсе:
    либо экземпляр ещё поднимается, либо он завис.
    """
    window = foreground.find(title)
    if not window:
        return False

    return foreground.force(window)
