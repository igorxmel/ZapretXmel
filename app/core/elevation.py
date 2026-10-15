"""Права администратора.

Они нужны и для `sc create`, и для драйвера WinDivert при запуске winws
напрямую, поэтому приложение целиком работает в элевированном процессе.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

from app.core import paths

log = logging.getLogger(__name__)

SW_SHOWNORMAL = 1


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def relaunch_as_admin() -> bool:
    """Перезапускает приложение через UAC.

    Возвращает True, если запрос принят — тогда текущий процесс нужно закрыть.
    False означает, что пользователь отказал или UAC недоступен.
    """
    executable = sys.executable
    extra = [f'"{arg}"' for arg in sys.argv[1:]]

    if getattr(sys, "frozen", False):
        params = " ".join(extra)
        workdir = str(Path(sys.executable).resolve().parent)
    else:
        # Пакет запускается через -m из корня проекта. Передавать путь к
        # app/__main__.py нельзя: тогда в sys.path попадёт папка app, корень
        # проекта в него не войдёт, и `from app import ...` развалится ещё до
        # первой строки лога — а под pythonw это падение никак не видно.
        params = " ".join(["-m", "app", *extra])
        workdir = str(paths.app_root())

    log.info("Перезапуск через UAC: %s %s (рабочая папка %s)", executable, params, workdir)

    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, params, workdir, SW_SHOWNORMAL
        )
    except (AttributeError, OSError):
        log.exception("Не удалось запросить права администратора")
        return False

    # ShellExecuteW возвращает значение больше 32 при успехе.
    return result > 32
