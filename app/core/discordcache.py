"""Очистка кеша Discord.

После смены стратегии Discord иногда продолжает «не подключаться»: клиент держит в
кеше ответы, полученные, пока соединения резались, и не перезапрашивает их. Помогает
закрыть его и удалить кеш — так советуют и в сообществе zapret.

Удаляются только папки кеша. Вход, настройки и сообщения лежат в других папках и
остаются на месте.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

import psutil

from app.core.nettools import Outcome

log = logging.getLogger(__name__)

# Обычный Discord, тестовые сборки и их процессы.
CLIENTS = ("discord", "discordptb", "discordcanary")
PROCESSES = ("discord.exe", "discordptb.exe", "discordcanary.exe")
CACHE_FOLDERS = ("Cache", "Code Cache", "GPUCache")


def roaming() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))


def cache_dirs() -> list[Path]:
    """Папки кеша установленных клиентов, которые существуют."""
    return [
        roaming() / client / folder
        for client in CLIENTS
        for folder in CACHE_FOLDERS
        if (roaming() / client / folder).is_dir()
    ]


def running() -> list[psutil.Process]:
    found = []
    for process in psutil.process_iter(["name"]):
        name = (process.info.get("name") or "").lower()
        if name in PROCESSES:
            found.append(process)
    return found


def _close(processes: list[psutil.Process], wait: float = 5.0) -> None:
    """Закрывает Discord: пока он запущен, файлы кеша заняты и не удаляются."""
    for process in processes:
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _gone, alive = psutil.wait_procs(processes, timeout=wait)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if alive:
        psutil.wait_procs(alive, timeout=2)


def _size(folder: Path) -> int:
    total = 0
    for path in folder.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def clear() -> Outcome:
    """Закрывает Discord и удаляет его кеш. Запустить Discord человек должен сам."""
    folders = cache_dirs()
    if not folders:
        return Outcome(
            "Кеш Discord",
            "чистить нечего",
            "Папок кеша Discord не нашлось: он не установлен или кеш уже пуст.",
        )

    was_running = running()
    if was_running:
        _close(was_running)
        time.sleep(0.5)

    freed = 0
    failed: list[str] = []
    for folder in folders:
        size = _size(folder)
        shutil.rmtree(folder, ignore_errors=True)
        if folder.exists():
            failed.append(str(folder))
        else:
            freed += size
    log.info("Кеш Discord очищен: %d байт, не удалось: %s", freed, failed)

    detail = f"Освобождено {freed / 1048576:.0f} МБ. Запустите Discord заново."
    if was_running:
        detail = "Discord был закрыт. " + detail
    if failed:
        return Outcome(
            "Кеш Discord",
            "очищен не весь",
            detail + " Часть файлов занята — закройте Discord в трее и повторите.",
            "warning",
            lines=failed,
        )
    return Outcome("Кеш Discord", "очищен", detail)
