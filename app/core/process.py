"""Запуск дочерних процессов, которые не должны пережить приложение.

И winws, и прокси для Telegram помещаются в Job Object с флагом
KILL_ON_JOB_CLOSE: если приложение упадёт, Windows снимет их сама. Иначе в
системе остаётся работающий обход, который потом ищут через диспетчер задач и
не могут понять, почему сеть ведёт себя странно.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_ALL_ACCESS = 0x1F0FFF


# Сколько ждать, пока процесс закроется сам, прежде чем снимать силой.
CLOSE_TIMEOUT = 3.0

_WM_CLOSE = 0x0010


def ask_to_close(pid: int) -> bool:
    """Просит окна процесса закрыться. False — просить было нечего.

    Нужно тем программам, которые что-то убирают за собой при выходе:
    у tg-ws-proxy это значок в трее Windows, который иначе остаётся висеть
    фантомом до первого движения мышью по нему.

    Окно ищем перебором верхнеуровневых: своего окна у дочернего процесса мы
    не знаем, а спрашивать его у системы по идентификатору процесса штатных
    способов нет.
    """
    if sys.platform != "win32":
        return False

    user32 = ctypes.windll.user32
    asked = False

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(window, _param):
        nonlocal asked
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == pid:
            user32.PostMessageW(window, _WM_CLOSE, 0, 0)
            asked = True
        return True

    try:
        user32.EnumWindows(visit, 0)
    except OSError:
        log.debug("Не удалось перебрать окна процесса %s", pid)
        return False

    return asked


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.POINTER(wintypes.ULONG)),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def create_kill_on_close_job() -> int | None:
    """Создаёт Job Object, который снимет дочерние процессы вместе с нами."""
    try:
        kernel32 = ctypes.windll.kernel32
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None

        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(job)
            return None
        return job
    except (AttributeError, OSError):
        log.exception("Не удалось создать Job Object")
        return None


def assign_to_job(job: int, pid: int) -> None:
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(_PROCESS_ALL_ACCESS, False, pid)
        if handle:
            kernel32.AssignProcessToJobObject(job, handle)
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        log.warning("Процесс %d не удалось привязать к Job Object", pid)


def close_job(job: int | None) -> None:
    if job:
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.kernel32.CloseHandle(job)


def child_environment() -> dict[str, str]:
    """Окружение для запуска другой программы из собранной версии.

    Собранная одним файлом программа распаковывает себя во временную папку и
    оставляет её путь в переменной `_MEIPASS2`. Дочерний процесс, увидев эту
    переменную, решает, что распаковывать нечего, и работает с чужой папкой —
    а она исчезает, как только закроется родитель. Так обновление и ломалось:
    новая версия падала с «no Qt platform plugin could be initialized», а
    старая не могла убрать за собой `_MEI…`.

    Заодно вычищаем из путей саму временную папку: туда же прописан поиск
    библиотек и плагинов Qt.
    """
    environment = dict(os.environ)
    temporary = getattr(sys, "_MEIPASS", "")

    environment.pop("_MEIPASS2", None)
    environment.pop("_PYI_APPLICATION_HOME_DIR", None)
    environment.pop("_PYI_ARCHIVE_FILE", None)

    # Значения, которые сборка подменила, она же сохранила рядом с суффиксом.
    for key in list(environment):
        if not key.endswith("_ORIG"):
            continue
        original = environment.pop(key)
        if original:
            environment[key[: -len("_ORIG")]] = original
        else:
            environment.pop(key[: -len("_ORIG")], None)

    if not temporary:
        return environment

    for key, value in list(environment.items()):
        if temporary.lower() not in value.lower():
            continue
        kept = [
            part for part in value.split(os.pathsep) if temporary.lower() not in part.lower()
        ]
        if kept:
            environment[key] = os.pathsep.join(kept)
        else:
            environment.pop(key, None)

    return environment


class ManagedProcess:
    """Дочерний процесс без консольного окна, с перехватом вывода."""

    def __init__(self, on_output: Callable[[str], None] | None = None, buffer_size: int = 500):
        self._process: subprocess.Popen[str] | None = None
        self._job: int | None = None
        self._reader: threading.Thread | None = None
        self._on_output = on_output
        self.output: deque[str] = deque(maxlen=buffer_size)

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, command: list[str], cwd: Path | None = None) -> None:
        if self.is_alive():
            raise RuntimeError("процесс уже запущен")

        self._job = create_kill_on_close_job()
        self._process = subprocess.Popen(  # noqa: S603 — команда собирается приложением
            command,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
            env=child_environment(),
        )

        if self._job:
            assign_to_job(self._job, self._process.pid)

        self._reader = threading.Thread(target=self._pump_output, daemon=True)
        self._reader.start()

    def _pump_output(self) -> None:
        process = self._process
        if not process or not process.stdout:
            return
        for line in process.stdout:
            text = line.rstrip()
            if not text:
                continue
            self.output.append(text)
            if self._on_output:
                self._on_output(text)

    def stop(self, timeout: float = 5.0) -> None:
        process, self._process = self._process, None

        if process and process.poll() is None:
            try:
                # Сначала просим закрыться по-человечески. TerminateProcess,
                # который стоит за terminate(), не даёт программе ни одной
                # инструкции на прощание — а tg-ws-proxy держит свой значок
                # в трее Windows и убирает его сам при закрытии. Убитый
                # насмерть, он оставлял там фантом: значок висит, пока по
                # нему не проведут мышью.
                if ask_to_close(process.pid):
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=CLOSE_TIMEOUT)

                if process.poll() is not None:
                    close_job(self._job)
                    self._job = None
                    return

                process.terminate()
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
            except OSError:
                log.warning("Не удалось корректно остановить процесс")

        close_job(self._job)
        self._job = None
