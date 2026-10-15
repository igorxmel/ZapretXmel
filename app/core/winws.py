"""Запуск winws напрямую, без службы и без консольного окна.

Процесс помещается в Job Object (см. `app.core.process`): если приложение
упадёт, Windows сама снимет winws, и в системе не останется висящего обхода,
который потом ищут через диспетчер задач.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import psutil

from app.core import paths
from app.core.batfile import StrategySpec
from app.core.process import CREATE_NO_WINDOW, ManagedProcess

log = logging.getLogger(__name__)

PROCESS_NAME = "winws.exe"

@dataclass(frozen=True)
class Instance:
    """Сведения о запущенном процессе winws — своём или чужом."""

    pid: int
    exe: str
    cmdline: list[str]


def find_instances() -> list[Instance]:
    """Все процессы winws в системе, включая запущенные другими оболочками."""
    found: list[Instance] = []
    for process in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            if (process.info["name"] or "").lower() != PROCESS_NAME:
                continue
            found.append(
                Instance(
                    pid=process.pid,
                    exe=process.info["exe"] or "",
                    cmdline=list(process.info["cmdline"] or []),
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def count_instances() -> int:
    """Быстрый подсчёт процессов winws.

    В отличие от `find_instances`, не запрашивает командные строки: psutil
    добывает их через обращение к памяти каждого процесса, и на опросе раз в
    несколько секунд это заметно подтормаживает систему.
    """
    total = 0
    for process in psutil.process_iter(["name"]):
        try:
            if (process.info["name"] or "").lower() == PROCESS_NAME:
                total += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def is_running() -> bool:
    return count_instances() > 0


def kill_all(timeout: float = 5.0) -> int:
    """Снимает все процессы winws. Возвращает число снятых."""
    victims: list[psutil.Process] = []
    for instance in find_instances():
        try:
            victims.append(psutil.Process(instance.pid))
        except psutil.NoSuchProcess:
            continue

    for process in victims:
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    _, alive = psutil.wait_procs(victims, timeout=timeout)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return len(victims)


def wait_until_ready(timeout: float = 5.0) -> bool:
    """Ждёт появления процесса winws после запуска стратегии.

    Пауза после обнаружения повторяет поведение апстримного тестера: процессу
    нужно время, чтобы открыть драйвер WinDivert и начать перехват.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running():
            time.sleep(0.3)
            return True
        time.sleep(0.2)
    return False


def restore(instances: Iterable[Instance]) -> int:
    """Возвращает к жизни чужие инстансы winws, снятые на время тестов."""
    current = {tuple(inst.cmdline) for inst in find_instances()}
    restored = 0

    for instance in instances:
        if not instance.exe or tuple(instance.cmdline) in current:
            continue
        try:
            subprocess.Popen(  # noqa: S603 — команда собрана из снятого снимка
                instance.cmdline,
                cwd=str(Path(instance.exe).parent),
                creationflags=CREATE_NO_WINDOW,
            )
            restored += 1
        except OSError:
            log.warning("Не удалось восстановить winws: %s", instance.exe)

    return restored


class WinwsProcess(ManagedProcess):
    """Запущенный нами экземпляр winws с перехватом вывода."""

    def start(self, spec: StrategySpec, exe: Path | None = None, cwd: Path | None = None) -> None:
        """Запускает winws с аргументами разобранной стратегии."""
        if self.is_alive():
            raise RuntimeError("winws уже запущен этим приложением")

        exe = exe or paths.winws_exe()
        if not exe.exists():
            raise FileNotFoundError(f"не найден {exe}")

        log.info("Запуск winws: стратегия %s, %d аргументов", spec.name, len(spec.argv))
        # Рабочая папка — корень сборки: относительные пути в стратегиях
        # разворачиваются именно от него.
        super().start([str(exe), *spec.argv], cwd=cwd or exe.parent.parent)
