"""Запуск программы вместе с Windows.

Очевидный способ — ключ `Run` в реестре — здесь не работает, и это не
случайность. Программа собрана с требованием прав администратора: она
создаёт службу и грузит драйвер. Windows не поднимает такие программы из
`Run` при входе в систему — показать запрос UAC посреди загрузки рабочего
стола некому, и запись просто игнорируется. Со стороны выглядит как
«галочка есть, автозапуск не работает».

Поэтому задача в планировщике с флагом «с наивысшими правами»: он для того
и придуман. Старую запись в `Run` убираем — она осталась у тех, кто ставил
галочку раньше, и ничего не делает.
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
import sys
import winreg
from pathlib import Path

from app.core import elevation, paths
from app.core.process import CREATE_NO_WINDOW, child_environment

log = logging.getLogger(__name__)

TASK_NAME = "ZapretXmel"

# Прежний способ: оставлен только затем, чтобы убрать за собой.
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "ZapretXmel"


def _target() -> str:
    if getattr(sys, "frozen", False):
        return str(paths.executable())
    return f'"{sys.executable}" "{Path(sys.argv[0]).resolve()}"'


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 — фиксированная системная утилита
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        creationflags=CREATE_NO_WINDOW,
        env=child_environment(),
        check=False,
    )


def enabled() -> bool:
    """Есть ли задача автозапуска."""
    try:
        result = _run(["schtasks", "/query", "/tn", TASK_NAME])
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _drop_legacy_run_key() -> None:
    """Убирает запись в `Run`, оставшуюся от прежних версий."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key, contextlib.suppress(FileNotFoundError):
            winreg.DeleteValue(key, _RUN_VALUE)
    except OSError:
        log.debug("Старую запись автозапуска убрать не удалось")


def set_enabled(wanted: bool) -> bool:
    """Создаёт или убирает задачу. False — не получилось."""
    _drop_legacy_run_key()

    try:
        if not wanted:
            result = _run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])
            # Задачи и так нет — это не ошибка, результат тот же.
            return result.returncode == 0 or not enabled()

        if not elevation.is_admin():
            log.warning("Задачу автозапуска создаёт только администратор")
            return False

        result = _run(
            [
                "schtasks",
                "/create",
                "/tn",
                TASK_NAME,
                "/tr",
                _target(),
                "/sc",
                "onlogon",
                # Без этого задача запустится без прав, и программа тут же
                # попросит их у человека — то есть ровно то, чего мы избегали.
                "/rl",
                "highest",
                "/f",
            ]
        )
        if result.returncode != 0:
            log.warning("Планировщик отказал: %s", result.stdout.strip() or result.stderr.strip())
            return False

        log.info("Автозапуск: задача %s создана", TASK_NAME)
        return True
    except (OSError, subprocess.SubprocessError):
        log.exception("Не удалось изменить автозапуск")
        return False


def retarget() -> None:
    """Перенацеливает задачу после переезда программы в другую папку."""
    if enabled():
        set_enabled(True)
