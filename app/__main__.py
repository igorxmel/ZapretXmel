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
from PyQt6.QtWidgets import QApplication, QMessageBox

from app import logging_setup
from app.core import elevation, paths
from app.core.config import Settings
from app.core.updater import selfupdate
from app.ui.theme import build_stylesheet

log = logging.getLogger(__name__)

APP_ID = "ZapretXmel.Bypass.GUI.1"


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

    QMessageBox.critical(
        None,
        "Нужны права администратора",
        "ZapretXmel управляет службой Windows и загружает драйвер WinDivert — "
        "без прав администратора это невозможно.\n\n"
        "Запустите приложение ещё раз и подтвердите запрос системы.",
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
            QMessageBox.critical(
                None,
                "ZapretXmel: сбой",
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"Подробности в файле {paths.logs_dir() / 'app.log'}",
            )

    sys.excepthook = handle


def main() -> int:
    paths.ensure_dirs()
    logging_setup.setup()
    install_crash_handler()
    log.info("Запуск ZapretXmel (admin=%s)", elevation.is_admin())

    # Файл прошлой версии удаляется здесь: пока программа работала,
    # сделать это было нельзя.
    selfupdate.cleanup()

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

    if not ensure_admin(app, skip=skip_elevation):
        return 0

    settings = Settings.load()

    from app.ui.shell import MainWindow

    window = MainWindow(settings)
    if settings.start_minimized:
        window.hide()
    else:
        window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
