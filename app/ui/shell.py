"""Главное окно: боковое меню и переключение экранов."""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core import foreground, updates
from app.core.config import Settings
from app.ui.controller import Controller, Status
from app.ui.frameless import FramelessWindow
from app.ui.theme.tokens import COLORS, SIZE, SPACE
from app.ui.tray import Tray, app_icon, build_icon
from app.ui.views.autopick import AutoPickView
from app.ui.views.dashboard import DashboardView
from app.ui.views.diagnostics import DiagnosticsView
from app.ui.views.lists import ListsView
from app.ui.views.logs import LogsView
from app.ui.views.profiles import ProfilesView
from app.ui.views.settings import SettingsView
from app.ui.views.strategies import StrategiesView
from app.ui.views.support import SupportView
from app.ui.views.telegram import TelegramView
from app.ui.views.updates import UpdatesView
from app.ui.views.welcome import WelcomeWindow
from app.ui.widgets import banner_pixmap
from app.ui.workers import Task

log = logging.getLogger(__name__)

# Пауза перед проверкой обновлений: см. `_look_for_updates`.
UPDATE_CHECK_DELAY_MS = 60_000

TOAST_MS = 6000


class MainWindow(FramelessWindow):
    """Окно приложения.

    Экраны создаются сразу все: их немного, а переключение без задержки важнее
    экономии нескольких мегабайт памяти.
    """

    def __init__(self, settings: Settings):
        super().__init__("ZapretXmel")
        self.settings = settings
        self.controller = Controller(settings, self)
        self._quitting = False
        self._updates_task: Task | None = None

        self.setWindowIcon(app_icon())
        self.setMinimumSize(SIZE["window_min_width"], SIZE["window_min_height"])
        self.resize(SIZE["window_width"], SIZE["window_height"])

        self._build_ui()
        self._build_tray()
        self._connect()

        self.controller.start_polling()
        QTimer.singleShot(0, self._first_run)

    # --- сборка ---------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self.body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["lg"])
        content_layout.setSpacing(SPACE["md"])

        self._stack = QStackedWidget()
        self.views = {
            "dashboard": DashboardView(self.controller),
            "strategies": StrategiesView(self.controller),
            "autopick": AutoPickView(self.controller),
            "lists": ListsView(self.controller),
            "profiles": ProfilesView(self.controller),
            "telegram": TelegramView(self.controller),
            "diagnostics": DiagnosticsView(self.controller),
            "updates": UpdatesView(self.controller),
            "settings": SettingsView(self.controller),
            "support": SupportView(self.controller),
            "logs": LogsView(self.controller),
        }
        for view in self.views.values():
            self._stack.addWidget(view)

        content_layout.addWidget(self._stack, 1)

        self._toast = QLabel("")
        self._toast.setObjectName("Muted")
        self._toast.setWordWrap(True)
        content_layout.addWidget(self._toast)

        root.addWidget(content, 1)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(SIZE["sidebar_width"])

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, SPACE["xl"])
        layout.setSpacing(0)

        # Название нарисовано прямо на баннере, поэтому отдельной подписи
        # рядом нет: иначе логотип и имя программы повторялись бы дважды —
        # здесь и в заголовке окна.
        header = QFrame()
        header.setObjectName("SidebarHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(SPACE["md"], SPACE["md"], SPACE["md"], SPACE["md"])
        header_layout.setSpacing(SPACE["xs"])

        banner = QLabel()
        banner.setPixmap(banner_pixmap(SIZE["sidebar_width"] - SPACE["md"] * 2))
        banner.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        header_layout.addWidget(banner)

        version = QLabel(f"версия {__version__}")
        version.setObjectName("SidebarVersion")
        version.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        header_layout.addWidget(version)

        # Линия идёт от края до края меню, поэтому полей вокруг шапки нет.
        layout.addWidget(header)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        entries = (
            ("dashboard", "Обзор"),
            ("strategies", "Стратегии"),
            ("autopick", "Подбор стратегии"),
            ("lists", "Списки"),
            ("profiles", "Приложения"),
            ("telegram", "Telegram"),
            ("diagnostics", "Диагностика"),
            ("updates", "Обновления"),
            ("settings", "Настройки"),
            ("support", "Поддержка"),
            ("logs", "Логи"),
        )
        self._nav_buttons: dict[str, QPushButton] = {}

        for key, title in entries:
            button = QPushButton(title)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _, target=key: self.navigate(target))
            self._nav_group.addButton(button)
            self._nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        self._sidebar_state = QLabel("")
        self._sidebar_state.setObjectName("SidebarVersion")
        self._sidebar_state.setWordWrap(True)
        layout.addWidget(self._sidebar_state)

        return sidebar

    def _build_tray(self) -> None:
        self._tray = Tray(self.controller, self)
        self._tray.show_requested.connect(self._restore_window)
        self._tray.quit_requested.connect(self.quit)
        self._tray.show()

    def _connect(self) -> None:
        self.controller.message.connect(lambda text: self._show_toast(text, COLORS["text_dim"]))
        self.controller.error.connect(lambda text: self._show_toast(text, COLORS["danger"]))
        self.controller.status_changed.connect(self._apply_status)
        self.views["dashboard"].navigate.connect(self.navigate)
        self.views["dashboard"].install_core_requested.connect(self._install_core)
        self.controller.foreign_conflict.connect(self._ask_about_foreign)
        self.controller.watch_alert.connect(self._watch_alert)

    # --- поведение ------------------------------------------------------

    def navigate(self, key: str) -> None:
        view = self.views.get(key)
        if view is None:
            return

        self._stack.setCurrentWidget(view)
        if button := self._nav_buttons.get(key):
            button.setChecked(True)

        # Экраны перечитывают данные при открытии: состояние сборки меняется
        # и снаружи приложения — через консольное меню или другой GUI.
        if reload_method := getattr(view, "reload", None):
            reload_method()
        if key == "logs":
            view.load_tail(self.controller.status.log_tail)

    def _watch_alert(self, message: str, switched: bool) -> None:
        """Показывает сообщение сторожа.

        И в окне, и в трее: окно может быть свёрнуто, а новость из тех, из-за
        которых человек и полезет в программу.
        """
        self._show_toast(message, COLORS["warning"])
        self._tray.showMessage(
            "ZapretXmel",
            message,
            build_icon(self.controller.status.is_active),
            8000,
        )
        if switched:
            log.info("Сторож переключил стратегию: %s", message)

    def _ask_about_foreign(self, path: str) -> None:
        """Спрашивает разрешение подвинуть другую установку zapret.

        Служба у неё и у нас одна и та же, так что включение обхода её
        пересоздаёт. Человек, который до этого пользовался zapret вручную,
        должен узнать об этом до, а не после.
        """
        question = QMessageBox(self)
        question.setWindowTitle("На компьютере уже есть zapret")
        question.setIcon(QMessageBox.Icon.Warning)
        question.setText(f"Обходом сейчас управляет установка в {path}.")
        question.setInformativeText(
            "Служба Windows у неё и у нас называется одинаково, поэтому включение "
            "обхода здесь пересоздаст её на нашу копию, а в режиме обычного "
            "процесса ещё и остановит её winws.\n\n"
            "Прежняя установка никуда не денется: её консольное меню сможет "
            "вернуть службу себе. Свои списки доменов стоит перенести заранее — "
            "в разделе «Списки» есть импорт из другой папки zapret."
        )

        replace = question.addButton(
            "Переключить на эту программу", QMessageBox.ButtonRole.AcceptRole
        )
        question.addButton("Оставить как есть", QMessageBox.ButtonRole.RejectRole)
        question.exec()

        if question.clickedButton() is replace:
            self.controller.start(replace_foreign=True)

    def _install_core(self) -> None:
        """Ставит ядро по нажатию главной кнопки, когда его ещё нет."""
        self.navigate("updates")
        self.views["updates"].install_core()

    def _first_run(self) -> None:
        status = self.controller.refresh()
        self.navigate("dashboard")

        if not self.settings.first_run_done:
            self.show_welcome()
            return

        # Служба стартует вместе с Windows сама, поэтому включать нечего —
        # это нужно только режиму обычного процесса.
        if self.settings.start_bypass_on_launch and status.core_present and not status.is_active:
            self._show_toast("Включаю обход…", COLORS["text_dim"])
            QTimer.singleShot(0, self.controller.start)

        self._look_for_updates()

    def _look_for_updates(self) -> None:
        """Проверяет обновления в фоне, через минуту после запуска.

        Сразу — нельзя: при старте программа и так опрашивает службу, читает
        ядро и, если попросили, поднимает обход. Задержка нужна и по смыслу:
        сообщение о новой версии в первую секунду перебивает то, ради чего
        программу открыли.
        """
        if not self.settings.notify_updates:
            return

        def start() -> None:
            self._updates_task = Task(updates.check_all)
            self._updates_task.done.connect(self._updates_found)
            self._updates_task.start()

        QTimer.singleShot(UPDATE_CHECK_DELAY_MS, start)

    def _updates_found(self, found: list) -> None:
        if not found:
            return

        text = updates.summary(found)
        self._show_toast(f"{text} — загляните в «Обновления»", COLORS["warning"])
        self._tray.showMessage(
            "ZapretXmel",
            text,
            build_icon(self.controller.status.is_active),
            6000,
        )

    def show_welcome(self) -> None:
        """Открывает знакомство — при первом запуске и по кнопке из настроек."""
        self._welcome = WelcomeWindow(self.controller, self)
        self._welcome.navigate.connect(self.navigate)
        self._welcome.refresh()
        self._welcome.show()
        # Знакомство модальное и всплывает поверх главного окна само, но если
        # вперёд не пустили всё приложение целиком, оно окажется позади чужих
        # окон вместе с ним.
        foreground.force(int(self._welcome.winId()))

    def _apply_status(self, status: Status) -> None:
        self._sidebar_state.setText(status.state_label)
        self._sidebar_state.setStyleSheet(
            f"color: {COLORS['success'] if status.is_active else COLORS['text_muted']};"
            f"padding: 0 {SPACE['lg']}px;"
        )

    def _show_toast(self, text: str, color: str) -> None:
        self._toast.setText(text)
        self._toast.setStyleSheet(f"color: {color};")
        QTimer.singleShot(TOAST_MS, lambda: self._clear_toast(text))

    def _clear_toast(self, text: str) -> None:
        if self._toast.text() == text:
            self._toast.setText("")

    def present(self) -> None:
        """Показывает окно и выводит его вперёд.

        Одного `show()` мало: после перезапуска через UAC процесс новый, а
        активное окно осталось за чужой программой — Windows в таком случае
        поднимать окно запрещает, и оно открывается где-то позади. Поэтому
        просим систему отдельно (`app/core/foreground.py`).
        """
        self.showNormal()
        self.raise_()
        self.activateWindow()
        foreground.force(int(self.winId()))

    def _restore_window(self) -> None:
        self.present()

    def quit(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — имя задано Qt
        # Уведомление о сворачивании в трей не показываем: человек сам
        # закрыл окно, значок в трее у него перед глазами, и всплывающая
        # подсказка каждый раз сообщала бы то, что и так видно.
        if self.settings.minimize_to_tray and not self._quitting:
            event.ignore()
            self.hide()
            return

        self.controller.shutdown()
        self._tray.hide()
        event.accept()

        # Выход из цикла событий обязан быть явным. Приложение живёт без окон
        # намеренно (`setQuitOnLastWindowClosed(False)`) — иначе сворачивание в
        # трей завершало бы его. Но без этой строки закрытое окно оставляло
        # процесс в памяти навсегда: невидимый, без значка в трее и с занятым
        # мьютексом, из-за которого следующий запуск молча ничего не делал.
        QApplication.quit()

    # Свёрнутое окно остаётся на панели задач — там ему и место. Раньше оно
    # пряталось в трей при любом сворачивании, хотя настройка обещает это
    # только взамен закрытия: кнопка «свернуть» переставала работать так,
    # как работает везде в Windows.

