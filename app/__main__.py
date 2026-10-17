"""Точка входа.

Приложение целиком работает с правами администратора: они нужны и для
управления службой, и для драйвера WinDivert при запуске winws напрямую.
Поэтому при обычном запуске процесс сразу перезапускается через UAC.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app import logging_setup
from app.core import elevation, location, paths, singleton
from app.core.config import Settings
from app.core.updater import selfupdate
from app.ui import dialogs, motion
from app.ui.theme import build_stylesheet
from app.ui.widgets import WheelGuard

log = logging.getLogger(__name__)

# Он же подписывает уведомления Windows, если программа не
# зарегистрирована ярлыком: в шапке всплывающего окна человек видел
# «ZapretXmel.Bypass.GUI.1». Поэтому имя, а не путь из точек.
APP_ID = "ZapretXmel"


def ensure_admin(app: QApplication, skip: bool = False) -> bool:
    """Возвращает True, если можно продолжать работу в текущем процессе."""
    if elevation.is_admin():
        return True

    if skip:
        log.warning("Запуск без прав администратора: управление обходом будет недоступно")
        return True

    if elevation.relaunch_as_admin():
        log.info("Перезапуск с правами администратора")
        return False

    dialogs.tell(
        None,
        "Нужны права администратора",
        "Без прав администратора обходом управлять нельзя.",
        "ZapretXmel создаёт службу Windows и загружает драйвер WinDivert — "
        "и то, и другое требует прав администратора.\n\n"
        "Запустите программу ещё раз и подтвердите запрос системы.",
        tone="warning",
    )
    app.quit()
    return False


def set_app_identity() -> None:
    """Объявляет Windows, что это отдельное приложение.

    Без собственного AppUserModelID система считает приложением сам
    `pythonw.exe` и склеивает нас с другими программами на нём: в трее и на
    панели задач показывается чужой значок, а окна группируются вместе.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        log.debug("Не удалось задать AppUserModelID")


def install_crash_handler() -> None:
    """Делает падения заметными.

    Под pythonw консоли нет, поэтому необработанное исключение иначе просто
    закрывает приложение без следа — именно так выглядит «ничего не произошло».
    """

    def handle(exc_type, exc_value, traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, traceback)
            return

        log.critical("Необработанная ошибка", exc_info=(exc_type, exc_value, traceback))
        with contextlib.suppress(Exception):  # на этом этапе показать может быть уже нечем
            dialogs.tell(
                None,
                "ZapretXmel: сбой",
                "Что-то сломалось так, что продолжать программа не может.",
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"Подробности — в журнале {paths.logs_dir() / 'app.log'}. "
                "Его стоит приложить к issue на GitHub: по нему видно, что "
                "именно случилось.",
                tone="danger",
            )

    sys.excepthook = handle


def revive_stuck_instance() -> bool:
    """Предлагает снять зависший экземпляр. True — можно продолжать запуск.

    Так выглядит «программа не открывается»: процесс в памяти есть, окна нет,
    мьютекс занят. Снимаем его только с согласия — вдруг экземпляр всего лишь
    не успел показать окно, и через мгновение покажет.
    """
    stuck = singleton.other_instances()
    if not stuck:
        dialogs.tell(
            None,
            "ZapretXmel уже запущен",
            "Программа уже работает, но окно ещё не появилось.",
            "Подождите несколько секунд и попробуйте ещё раз — или откройте "
            "её из значка в трее.",
        )
        return False

    if not dialogs.confirm(
        None,
        "ZapretXmel уже запущен",
        "Похоже, прошлый запуск завис.",
        "Программа есть в памяти, но её окно не отзывается. Завершить этот "
        "процесс и открыть программу заново?",
        action="Завершить и открыть",
    ):
        return False

    singleton.terminate_others()
    if singleton.acquire():
        return True

    dialogs.tell(
        None,
        "ZapretXmel",
        "Зависший процесс не удалось завершить.",
        "Снимите ZapretXmel.exe в диспетчере задач и запустите программу "
        "ещё раз.",
        tone="warning",
    )
    return False


def main() -> int:
    # Проверка собранной версии: никакого интерфейса, только убедиться, что
    # программа вообще запускается и все модули внутри .exe на месте. Иначе
    # сломанную сборку обнаруживает уже пользователь — окно просто не
    # открывается, а причина остаётся в диалоге, которого никто не видел.
    if "--version" in sys.argv:
        # Печатать нечего и некуда: у собранной без консоли программы
        # стандартного потока нет вовсе, и обычный print уронил бы её — ровно
        # тем диалогом, который эта проверка и должна ловить. Значение здесь
        # только в коде возврата: ноль означает, что все модули на месте.
        return 0

    paths.ensure_dirs()
    logging_setup.setup()
    install_crash_handler()
    log.info("Запуск ZapretXmel (admin=%s)", elevation.is_admin())

    # Файл прошлой версии удаляется здесь: пока программа работала,
    # сделать это было нельзя. По той же причине здесь убирается и то, что
    # осталось от прошлой папки после переезда на другой диск.
    selfupdate.cleanup()
    location.cleanup()

    # Флаг для разработки: позволяет открыть интерфейс без запроса UAC.
    # Управление обходом в таком режиме не работает — это ожидаемо.
    skip_elevation = "--no-elevate" in sys.argv

    set_app_identity()

    app = QApplication(sys.argv)
    app.setApplicationName("ZapretXmel")
    app.setApplicationDisplayName("ZapretXmel")
    app.setDesktopFileName("ZapretXmel")
    app.setWindowIcon(QIcon(str(paths.logo_file())))
    app.setQuitOnLastWindowClosed(False)

    # Стили вешаем на приложение, а не на окно: меню в трее создаётся без
    # родителя и оформление окна до него не доходит.
    app.setStyleSheet(build_stylesheet())

    # Колесо мыши не должно менять значения при прокрутке страницы.
    guard = WheelGuard(app)
    app.installEventFilter(guard)

    if not ensure_admin(app, skip=skip_elevation):
        return 0

    # Проверка повторного запуска идёт именно здесь, после решения вопроса о
    # правах: при перезапуске через UAC старый процесс ещё доживает свои
    # мгновения, и более ранняя проверка приняла бы его за чужой экземпляр.
    if not singleton.acquire():
        log.info("Программа уже запущена")
        if singleton.focus_existing():
            return 0
        # Мьютекс занят, а окна нет — экземпляр завис. Просто выйти здесь
        # нельзя: человек жмёт на ярлык, и ничего не происходит, причём
        # сколько угодно раз подряд.
        if not revive_stuck_instance():
            return 0

    settings = Settings.load()
    motion.set_enabled(settings.animations)

    from app.ui.shell import MainWindow

    window = MainWindow(settings)
    if settings.start_minimized:
        window.hide()
    else:
        window.present()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
