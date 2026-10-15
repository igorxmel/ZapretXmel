"""Профиль, который поднимается вместе с приложением.

Профиль приложения включают перед игрой и забывают выключить — или, чаще,
забывают включить вовсе, и потом удивляются, почему игра снова лагает.
Программа умеет сделать это сама: профиль записан для конкретного .exe, и
остаётся лишь заметить, что он запустился.

Опрос процессов стоит денег, поэтому он один на все профили и выполняется
только когда есть что искать — иначе каждый профиль добавлял бы свой проход
по списку процессов каждые несколько секунд.
"""

from __future__ import annotations

import logging
from pathlib import Path

import psutil

log = logging.getLogger(__name__)


def running_executables() -> set[str]:
    """Пути всех запущенных программ, приведённые к нижнему регистру.

    Один проход по процессам: сравнивать по пути, а не по имени файла,
    важно — `game.exe` в двух разных установках это две разные программы.
    """
    found: set[str] = set()
    for process in psutil.process_iter(["exe"]):
        try:
            path = process.info["exe"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if path:
            found.add(path.lower())
    return found


def is_running(executable: str, running: set[str]) -> bool:
    """Запущено ли приложение профиля.

    Путь мог измениться — игру перенесли или обновили лаунчером, — поэтому
    при промахе по полному пути сверяем имя файла.
    """
    if not executable:
        return False

    wanted = executable.lower()
    if wanted in running:
        return True

    name = Path(wanted).name
    return any(Path(path).name == name for path in running)


def decide(profile_exe: str, auto: bool, profile_active: bool, running: set[str]) -> str:
    """Что сделать с профилем: «start», «stop» или «» — ничего.

    Выключаем только то, что сами же и включили: профиль, поднятый руками,
    программа гасить не должна — человек мог оставить его намеренно.
    """
    if not auto or not profile_exe:
        return ""

    alive = is_running(profile_exe, running)
    if alive and not profile_active:
        return "start"
    if not alive and profile_active:
        return "stop"
    return ""
