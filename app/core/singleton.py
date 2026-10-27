"""Защита от второго запуска.

Два окна и два значка в трее — это не просто неопрятно: оба экземпляра начнут
управлять одной службой и одними файлами настроек, и чьи изменения уцелеют,
предсказать нельзя.

Поэтому первый запуск занимает именованный мьютекс, а второй, обнаружив его,
просит открытый экземпляр показать окно и тихо выходит. Мьютекс освобождается
системой при завершении процесса — даже если тот упал, так что «залипнуть» он
не может.

Окно показывает **сам первый экземпляр**, по именованному событию. Раньше второй
запуск находил окно по заголовку и показывал его снаружи, через Windows API. С
окном, спрятанным в трей, так делать нельзя: Qt считает его скрытым и ничего не
знает про показ в обход себя, окно появляется, но не отвечает на нажатия, а
`SetForegroundWindow` при этом нередко возвращает отказ, который принимали за
«окна нет» и объявляли прошлый запуск зависшим.
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

# Событие, которым второй запуск просит первый показать окно. Тот же префикс
# Local\\ по той же причине: у каждого сеанса своя копия.
ACTIVATE_EVENT_NAME = "Local\\ZapretXmel.Activate"

_EVENT_MODIFY_STATE = 0x0002
_WAIT_OBJECT_0 = 0

_ERROR_ALREADY_EXISTS = 183

# Мьютекс держится в переменной модуля намеренно: если дать сборщику мусора
# закрыть его, защита исчезнет посреди работы программы.
_handle: int | None = None
_event: int | None = None

# Признак «меня запустила прежняя копия, чтобы занять её место»: мьютекс у неё
# ещё занят, но это не повод считать её живым экземпляром.
RESTART_FLAG = "--restarted"


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

        won = kernel32.GetLastError() != _ERROR_ALREADY_EXISTS
        if won:
            _create_activation_event()
        return won
    except (AttributeError, OSError):
        log.debug("Проверка повторного запуска недоступна")
        return True


def _create_activation_event() -> None:
    """Создаёт событие, на которое отзовётся окно. Автосброс: одно подача — один показ."""
    global _event

    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = [
            wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR,
        ]
        if _event:
            kernel32.CloseHandle(_event)
        _event = kernel32.CreateEventW(None, False, False, ACTIVATE_EVENT_NAME)
    except (AttributeError, OSError):
        log.debug("Событие показа окна недоступно")
        _event = None


def signal_existing() -> bool:
    """Просит запущенный экземпляр показать окно. False — слушателя нет.

    Нет его у экземпляров прошлых версий и у того, что ещё не успел
    подняться: событие создаётся вместе с мьютексом, а слушатель стартует
    позже, и подача, пришедшая раньше, не пропадает — событие остаётся
    взведённым, пока его не заберут.
    """
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenEventW.restype = wintypes.HANDLE
        kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.SetEvent.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.OpenEventW(_EVENT_MODIFY_STATE, False, ACTIVATE_EVENT_NAME)
        if not handle:
            return False
        try:
            return bool(kernel32.SetEvent(handle))
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        return False


def wait_activation(timeout_ms: int) -> bool:
    """Ждёт просьбу показать окно. True — просьба пришла. Для потока-слушателя."""
    if not _event:
        # Ждать нечего: пауза нужна, чтобы слушатель не крутился вхолостую.
        import time

        time.sleep(timeout_ms / 1000)
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        return kernel32.WaitForSingleObject(_event, timeout_ms) == _WAIT_OBJECT_0
    except (AttributeError, OSError):
        return False


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
    """Просит запущенный экземпляр показать окно. False — достучаться не вышло.

    Первым делом — событие: окно покажет сам экземпляр, средствами Qt, и это
    работает и для спрятанного в трей. Прямой показ через Windows API остаётся
    только для экземпляров прошлых версий, у которых слушателя нет, и только для
    **видимого** окна: скрытое так показывать нельзя, оно появляется, но Qt о
    нём не знает и оно не отвечает на нажатия.

    Нашлось окно, но вывести его вперёд система отказалась — это не «окна нет».
    Foreground-замок Windows отказывает постоянно, и принимать отказ за зависание
    значило гонять человека через вопрос «завершить процесс?» без причины.
    """
    if signal_existing():
        return True

    window = foreground.find(title)
    if not window or not foreground.is_visible(window):
        return False

    foreground.force(window)
    return True
