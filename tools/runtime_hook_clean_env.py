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

# Ставится перед перезапуском: второй раз себя не перезапускаем даже
# если чистка чего-то не доглядела.
_MARK = "ZAPRETXMEL_RELAUNCHED"


def _foreign(value: str, mine: str) -> bool:
    """Правда, если в значении есть чужая временная папка сборки."""
    for part in value.split(os.pathsep):
        lowered = part.lower()
        if "_mei" in lowered and mine.lower() not in lowered:
            return True
    return False


def _inherited_from_another_build(mine: str) -> bool:
    # Главный признак — сама переменная `_MEIPASS2`. По ней загрузчик решает,
    # что распаковывать ничего не нужно, и берёт готовую папку: нашу
    # собственную он к этому моменту уже удалил из окружения, так что её
    # наличие означает ровно одно — нас запустила другая сборка, и работаем
    # мы в её папке. Сравнивать значение с `sys._MEIPASS` бесполезно: они
    # как раз совпадают, потому что чужую папку мы и получили.
    if os.environ.get("_MEIPASS2"):
        return True

    # Папка может достаться и иначе — через пути к библиотекам Qt.
    if _foreign(os.environ.get("PATH", ""), mine):
        return True

    return any(_foreign(os.environ.get(name, ""), mine) for name in _MARKERS)


def _clean(mine: str) -> dict:
    """Убирает из окружения чужие временные папки, не трогая свои.

    Чистить приходится по частям, а не по значению целиком: в `PATH`
    одновременно лежат и наша папка, и доставшаяся от запустившей нас
    программы. Пропустив такое значение, мы оставили бы чужую папку на
    месте — и перезапуск не помог бы, а повторился бы снова.
    """
    environment = dict(os.environ)
    for name in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE"):
        environment.pop(name, None)

    for key, value in list(environment.items()):
        if "_mei" not in value.lower():
            continue

        kept = [part for part in value.split(os.pathsep) if not _foreign(part, mine)]
        if kept:
            environment[key] = os.pathsep.join(kept)
        else:
            environment.pop(key, None)

    # Метка о перезапуске: если чужие пути почему-то переживут чистку,
    # программа запустится как есть, а не будет перезапускать себя по кругу.
    environment[_MARK] = "1"
    return environment


def _restart() -> None:
    mine = getattr(sys, "_MEIPASS", "")
    if not mine or os.environ.get(_MARK) or not _inherited_from_another_build(mine):
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
