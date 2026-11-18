"""Проверка собранной программы в сборке релиза: запуск целиком и самообновление.

`--version` только убеждается, что модули попали внутрь exe: он выходит раньше, чем
программа создаёт папки, читает настройки и строит окно. Поломки, которые доходили
до людей, были как раз дальше — запуск на чистой машине, данные прошлой версии,
подмена файла при обновлении. Здесь программа проходит путь человека:

- `--smoke` — обычный запуск, затем каждый раздел по очереди и штатный выход;
- `--smoke-update=<файл>` — то же, а перед выходом файл ставится как скачанное
  обновление: переносная подменяет свой exe, установленная запускает установщик.
  Новая версия стартует с `--smoke` и проверяет себя сама.

Итог каждого запуска — строкой в `data/logs/smoke.txt`: собранная без консоли
программа не может ничего напечатать, а код возврата перезапущенного экземпляра
никто не ждёт. Упала — код не ноль и строка `fail`, диалога нет: в сборке его
некому закрыть.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import traceback
from pathlib import Path

from app import __version__
from app.core import paths, singleton

log = logging.getLogger(__name__)

SMOKE_FLAG = "--smoke"
UPDATE_FLAG = "--smoke-update="
RESULT_NAME = "smoke.txt"

# Сколько дать программе прийти в себя: первый опрос состояния, окно знакомства.
SETTLE_MS = 4000
CRASH_CODE = 3
PROBLEM_CODE = 4


def requested() -> bool:
    return SMOKE_FLAG in sys.argv or update_source() is not None


def update_source() -> Path | None:
    for arg in sys.argv:
        if arg.startswith(UPDATE_FLAG):
            return Path(arg[len(UPDATE_FLAG):]).resolve()
    return None


def result_file() -> Path:
    return paths.logs_dir() / RESULT_NAME


def report(ok: bool, detail: str = "") -> None:
    restarted = singleton.RESTART_FLAG in sys.argv
    line = f"{'ok' if ok else 'fail'} {__version__} restarted={restarted} {detail}".rstrip()
    try:
        result_file().parent.mkdir(parents=True, exist_ok=True)
        with result_file().open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    log.info("Проверка сборки: %s", line)


def install_crash_exit() -> None:
    """Любое необработанное исключение — строка `fail` и выход, а не диалог."""

    def handle(exc_type, exc_value, tb) -> None:
        log.critical("Необработанная ошибка", exc_info=(exc_type, exc_value, tb))
        last = traceback.format_exception_only(exc_type, exc_value)[-1].strip()
        report(False, last)
        logging.shutdown()
        os._exit(CRASH_CODE)

    sys.excepthook = handle


def run(app, window) -> None:
    """Запускает проверку, когда окно поднялось."""
    from PyQt6.QtCore import QTimer

    QTimer.singleShot(SETTLE_MS, lambda: _check(app, window))


def _check(app, window) -> None:
    # Окно знакомства на чистой машине модальное: закрываем, как закрыл бы человек.
    for _ in range(5):
        modal = app.activeModalWidget()
        if modal is None:
            break
        modal.close()
        app.processEvents()

    problems = []
    for key in list(window.views):
        window.navigate(key)
        app.processEvents()
        if window._stack.currentWidget() is not window.views[key]:
            problems.append(f"раздел {key} не открылся")
    window.navigate("dashboard")
    app.processEvents()
    if not window.isVisible():
        problems.append("окно не видно")

    if problems:
        report(False, "; ".join(problems))
        logging.shutdown()
        os._exit(PROBLEM_CODE)

    source = update_source()
    if source is None:
        report(True)
        window.quit()
        return

    from app.core.updater import selfupdate

    try:
        staged = _stage(source)
        selfupdate.apply(staged)
        selfupdate.restart([SMOKE_FLAG])
    except Exception as error:  # noqa: BLE001 — любая причина — провал проверки
        report(False, f"обновление не поставилось: {error}")
        logging.shutdown()
        os._exit(PROBLEM_CODE)
    report(True, f"update={staged.name}")
    window.quit()


def _stage(source: Path) -> Path:
    """Кладёт файл туда же, куда его скачало бы обновление."""
    from app.core.updater import selfupdate

    if paths.is_installed():
        target = paths.data_dir() / "updates" / selfupdate.SETUP_NAME
    else:
        exe = selfupdate.executable()
        target = exe.with_suffix(selfupdate.NEW_SUFFIX + exe.suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target
