"""Проверка окружения до запуска программы.

Выполняется раньше всего остального кода, включая импорт Qt, — для этого
PyInstaller и держит механизм runtime-хуков.

Собранная одним файлом программа распаковывает себя во временную папку и
прописывает её в `PATH`, `QT_PLUGIN_PATH` и `QML2_IMPORT_PATH`. Когда одна
такая программа запускает другую, эти пути достаются ей по наследству: Qt
идёт искать плагины в чужую папку, которая исчезает вместе с родителем, и
новая версия падает с «no Qt platform plugin could be initialized», а старая
не может убрать за собой `_MEI…`.

Чинить это в той версии, которая запускает, поздно — она уже у людей.
Поэтому версия, которую запускают, умеет заметить чужие пути и перезапустить
себя сама, уже с чистым окружением.
"""

import os
import subprocess
import sys

# Переменные, по которым видно чужую временную папку. Собственную программа
# прописывает себе сама, и она совпадает с `sys._MEIPASS`.
_MARKERS = ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "_PYI_APPLICATION_HOME_DIR")


def _foreign(value: str, mine: str) -> bool:
    """Правда, если в значении есть чужая временная папка сборки."""
    for part in value.split(os.pathsep):
        lowered = part.lower()
        if "_mei" in lowered and mine.lower() not in lowered:
            return True
    return False


def _inherited_from_another_build(mine: str) -> bool:
    # PATH важнее остальных: из него берутся библиотеки Qt, и чужая папка в
    # начале списка подсовывает их из сборки, которая вот-вот исчезнет.
    if _foreign(os.environ.get("PATH", ""), mine):
        return True

    for name in _MARKERS:
        value = os.environ.get(name, "")
        if value and _foreign(value, mine):
            return True

    return bool(os.environ.get("_MEIPASS2", "")) and os.environ["_MEIPASS2"] != mine


def _clean(mine: str) -> dict:
    environment = dict(os.environ)
    for name in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE"):
        environment.pop(name, None)

    for key, value in list(environment.items()):
        if mine.lower() in value.lower() or "_mei" not in value.lower():
            continue
        kept = [part for part in value.split(os.pathsep) if "_mei" not in part.lower()]
        if kept:
            environment[key] = os.pathsep.join(kept)
        else:
            environment.pop(key, None)

    return environment


def _restart() -> None:
    mine = getattr(sys, "_MEIPASS", "")
    if not mine or not _inherited_from_another_build(mine):
        return

    executable = sys.executable
    try:
        subprocess.Popen(  # noqa: S603 — запускаем сами себя
            [executable, *sys.argv[1:]],
            close_fds=True,
            cwd=os.path.dirname(executable),
            env=_clean(mine),
        )
    except OSError:
        # Перезапуститься не вышло — пусть программа попробует работать как
        # есть: это всё равно лучше, чем закрыться молча.
        return

    # Выходим жёстко: обычный выход потянул бы за собой обработчики, которым
    # уже нечего делать, а Qt в этом процессе всё равно не поднимется.
    os._exit(0)


_restart()
