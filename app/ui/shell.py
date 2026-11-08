"""Главное окно: боковое меню и переключение экранов."""

from __future__ import annotations

import logging
import sys

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QTimer
from PyQt6.QtGui import QCloseEvent, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core import changelog, foreground, singleton, updates
from app.core.config import Settings
from app.core.updater import selfupdate
from app.ui import dialogs, motion
from app.ui.activation import ActivationListener
from app.ui.controller import Controller, Status
from app.ui.frameless import FramelessWindow, SvgCaptionButton
from app.ui.theme.tokens import BRAND, COLORS, SIZE, SPACE
from app.ui.tray import Tray, app_icon, build_icon
from app.ui.views import whatsnew
from app.ui.views.autopick import AutoPickView
from app.ui.views.dashboard import DashboardView
from app.ui.views.diagnostics import DiagnosticsView
from app.ui.views.help import HelpWindow
from app.ui.views.lists import ListsView
from app.ui.views.logs import LogsView
from app.ui.views.mini import MiniView
from app.ui.views.profiles import ProfilesView
from app.ui.views.settings import SettingsView
from app.ui.views.strategies import StrategiesView
from app.ui.views.support import SupportView
from app.ui.views.telegram import TelegramView
from app.ui.views.updates import UpdatesView
from app.ui.views.welcome import WelcomeWindow
from app.ui.widgets import NAV_MARK_WIDTH, Sidebar, banner_pixmap, spinner_icon
from app.ui.workers import Task

log = logging.getLogger(__name__)

# Пауза перед первой проверкой обновлений: см. `_look_for_updates`.
# Кружок загрузки в боковом меню: шаг и частота подобраны так, чтобы
# движение читалось, но не мельтешило.
# Разделы с долгой работой и то, как они называются в уведомлении.
BUSY_SECTIONS = {
    "autopick": "Подбор стратегии",
    "updates": "Обновление",
    "telegram": "Установка прокси",
}

# Переезд полоски в боковом меню. Длиннее, чем кажется нужным: на коротком
# переходе между соседними пунктами движение не успевает прочитаться.
NAV_SLIDE_MS = 240

SPINNER_INTERVAL_MS = 90
SPINNER_STEP = 30

UPDATE_CHECK_DELAY_MS = 60_000

# Дальше — раз в два часа: программа живёт в трее неделями, и одной
# проверки на запуск ей мало. Стоит это трёх запросов к GitHub за раз при
# лимите в шестьдесят в час, то есть ничего.
UPDATE_CHECK_INTERVAL_MS = 2 * 60 * 60 * 1000

# Автообновление не начинает работу, пока программа чем-то занята. Тогда
# спрашиваем ещё раз через пять минут: ждать два часа до следующей проверки
# незачем, находка уже на руках.
AUTO_UPDATE_RETRY_MS = 5 * 60 * 1000

TOAST_MS = 6000

# Разделы программы: боковое меню полного окна и меню мини-окна.
SECTIONS = (
    ("dashboard", "Обзор"),
    ("strategies", "Стратегии"),
    ("autopick", "Подбор стратегии"),
    ("lists", "Списки"),
    ("profiles", "Профили"),
    ("telegram", "Telegram"),
    ("diagnostics", "Диагностика"),
    ("updates", "Обновления"),
    ("settings", "Настройки"),
    ("support", "Поддержка"),
    ("logs", "Логи"),
)


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
        self._updates_manual = False
        # Перепроверка после установки: снимает поставленное, но не шумит.
        self._updates_quiet = False
        # Последняя находка: её отдают экранам, чтобы те не спрашивали
        # GitHub о том же самом второй раз.
        self._found_updates: list = []
        # Автообновление: что уже поставлено или не встало за этот запуск
        # («что», версия) — второй раз за то же не берёмся.
        self._auto_done: set[tuple[str, str]] = set()
        # Версия программы, которая уже стоит на месте старой и ждёт запуска.
        # Работающий экземпляр всё ещё старый, и проверка находила её снова.
        self._staged_app = ""
        # Окно «Что нового» отложено до первого показа окна: после тихого
        # перезапуска в трей оно всплыло бы само, а обещали молчать.
        self._whats_new_pending = False
        self._nav_ready = False
        self._current_section = "dashboard"
        self._compact = False
        # Размер полного окна: к нему возвращаемся из мини-режима.
        self._full_size: QSize | None = None
        self._help: HelpWindow | None = None
        # Разделы, где прямо сейчас идёт долгая работа. Нужны, чтобы
        # нарисовать кружок в боковом меню и сказать о завершении, если окно
        # успели свернуть.
        self._busy_sections: dict[str, str] = {}
        self._spin_angle = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(SPINNER_INTERVAL_MS)
        self._spin_timer.timeout.connect(self._spin)
        self._updates_timer = QTimer(self)
        self._updates_timer.timeout.connect(self._check_updates_now)

        self.setWindowIcon(app_icon())
        self._fit_to_screen()

        self._build_ui()
        self._build_tray()
        self._connect()
        self._build_corner_buttons()
        if settings.compact_mode:
            self.set_compact(True)

        # Повторный запуск не открывает второе окно, а просит это, — и показывать
        # его надлежит самому окну, иначе свёрнутое в трей не оживает (см. activation.py).
        self._activation = ActivationListener(self)
        self._activation.activated.connect(self.present)
        self._activation.start()

        self.controller.start_polling()
        QTimer.singleShot(0, self._first_run)

    # --- сборка ---------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self.body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Два вида одного окна: полный и мини. Окно и контроллер остаются теми же,
        # поэтому смена вида не трогает ни обход, ни идущую работу.
        #
        # Нарочно не QStackedWidget: его минимум считается по самой большой странице,
        # даже скрытой. Высокий раздел растягивал содержимое мини-окна ниже его края, и
        # кнопка меню уходила за низ. Скрытый виджет раскладка не учитывает вовсе.
        self._full_page = QWidget()
        outer.addWidget(self._full_page, 1)
        self._mini = MiniView(self.controller, SECTIONS)
        self._mini.hide()
        outer.addWidget(self._mini, 1)

        root = QHBoxLayout(self._full_page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["lg"])
        content_layout.setSpacing(SPACE["md"])

        content_layout.addWidget(self._build_update_banner())

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

    def _build_update_banner(self) -> QWidget:
        """Полоса о новой версии: висит, пока не обновились или не закрыли."""
        banner = QFrame()
        banner.setObjectName("UpdateBanner")
        banner.hide()

        row = QHBoxLayout(banner)
        row.setContentsMargins(SPACE["lg"], SPACE["sm"], SPACE["sm"], SPACE["sm"])
        row.setSpacing(SPACE["md"])

        self._update_text = QLabel("")
        self._update_text.setObjectName("UpdateBannerText")
        self._update_text.setWordWrap(True)
        row.addWidget(self._update_text, 1)

        open_updates = QPushButton("Перейти к обновлениям")
        open_updates.setObjectName("Primary")
        open_updates.clicked.connect(lambda: self.navigate("updates"))
        row.addWidget(open_updates)

        hide_banner = QPushButton("✕")
        hide_banner.setObjectName("BannerClose")
        hide_banner.setToolTip("Скрыть до следующей проверки")
        hide_banner.clicked.connect(banner.hide)
        row.addWidget(hide_banner)

        self._update_banner = banner
        return banner

    def _build_corner_buttons(self) -> None:
        """Справка и смена вида окна: нужны из любого раздела и в обоих видах."""
        help_button = SvgCaptionButton("window-help", "Как пользоваться")
        help_button.clicked.connect(self._open_help)

        self._compact_button = SvgCaptionButton("window-shrink", "Мини-окно")
        self._compact_button.clicked.connect(lambda: self.set_compact(not self._compact))

        self.titlebar.add_left(help_button, self._compact_button)

    def _open_help(self) -> None:
        if self._help is None:
            self._help = HelpWindow()
        self._help.show()
        self._help.raise_()
        self._help.activateWindow()

    def set_compact(self, compact: bool) -> None:
        """Переключает полное окно и мини-окно. Выбор запоминается."""
        if compact == self._compact:
            return

        if compact:
            if self.isMaximized():
                self.showNormal()
            # До первого показа размер ещё не настоящий: он считается по содержимому и
            # бывает больше экрана. Тогда при возврате просто подбираем его заново.
            if self.isVisible():
                self._full_size = self.size()

        self._compact = compact
        self.set_sizable(not compact)
        self._compact_button.set_icon("window-expand" if compact else "window-shrink")
        self._compact_button.setToolTip("Полное окно" if compact else "Мини-окно")

        if compact:
            self._full_page.hide()
            self._mini.show()
            self._mini.reload()
            self._mini.apply_status(self.controller.status)
            screen = self.screen() or QApplication.primaryScreen()
            room = screen.availableGeometry().height() if screen else SIZE["mini_height"]
            self.setFixedSize(SIZE["mini_width"], min(SIZE["mini_height"], int(room * 0.94)))
        else:
            self.setMaximumSize(16777215, 16777215)
            self._fit_to_screen()
            target = self._full_size or self.size()
            self.resize(target)
            # Страницу меняем уже в полном размере. Иначе раскладка считала перенос
            # строк по промежуточной ширине, и окно вырастало за край экрана.
            self._mini.hide()
            self._full_page.show()
            self.layout().activate()
            self.resize(target)
            self.views["dashboard"].reload()
            # Пока вид был скрыт, у кнопок меню не было настоящих мест.
            self._nav_ready = False
            QTimer.singleShot(0, self._place_nav_mark)

        self._keep_on_screen()

        if self.settings.compact_mode != compact:
            self.settings.compact_mode = compact
            self.settings.save()

    def _place_nav_mark(self) -> None:
        if button := self._nav_buttons.get(self._current_section):
            self._move_nav_mark(button)

    def _keep_on_screen(self) -> None:
        """Выросшее окно не должно уехать за край экрана."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None or not self.isVisible():
            return
        free = screen.availableGeometry()
        x = max(free.left(), min(self.x(), free.right() - self.width() + 1))
        y = max(free.top(), min(self.y(), free.bottom() - self.height() + 1))
        self.move(QPoint(x, y))

    def _hide_update_banner(self) -> None:
        """Убирает полосу вместе с подсветкой пункта меню.

        Кнопка «✕» на полосе этого не делает нарочно: человек отложил
        обновление, а не сделал его. Здесь другое — обновляться больше не
        на что.
        """
        self._update_banner.hide()
        self._mark_updates_nav(False)

    def _mark_updates_nav(self, alert: bool) -> None:
        if button := self._nav_buttons.get("updates"):
            button.setProperty("alert", alert)
            button.style().unpolish(button)
            button.style().polish(button)

    def _fit_to_screen(self) -> None:
        """Подбирает размер окна под экран, на котором его открывают.

        Размеры в токенах — для экрана без увеличения. При системном
        масштабе 125% Qt множит их сам, и окно по умолчанию оказывалось
        больше, чем рабочий стол ноутбука: заголовок за верхним краем,
        кнопки за нижним. Нижнюю границу тоже приходится опускать — иначе
        окно просто не помещается и его нельзя уменьшить.
        """
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.setMinimumSize(SIZE["window_min_width"], SIZE["window_min_height"])
            self.resize(SIZE["window_width"], SIZE["window_height"])
            return

        free = screen.availableGeometry()
        # Немного меньше рабочей области: окно должно читаться как окно, а
        # не как что-то, развёрнутое во весь экран.
        width = min(SIZE["window_width"], int(free.width() * 0.94))
        height = min(SIZE["window_height"], int(free.height() * 0.94))

        self.setMinimumSize(
            min(SIZE["window_min_width"], width),
            min(SIZE["window_min_height"], height),
        )
        self.resize(width, height)

    def _build_sidebar(self) -> QWidget:
        sidebar = Sidebar()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(SIZE["sidebar_width"])
        self._sidebar = sidebar

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

        self._nav_buttons: dict[str, QPushButton] = {}

        # Кнопки отступают от левого края ровно на ширину полоски: рисует её
        # сама панель, а дочерние виджеты всегда ложатся поверх родителя —
        # без этой полосы кнопка закрывала бы её целиком.
        nav = QVBoxLayout()
        nav.setContentsMargins(round(NAV_MARK_WIDTH), 0, 0, 0)
        nav.setSpacing(0)
        layout.addLayout(nav)

        for key, title in SECTIONS:
            button = QPushButton(title)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _, target=key: self.navigate(target))
            self._nav_group.addButton(button)
            self._nav_buttons[key] = button
            nav.addWidget(button)

        # Полоску у выбранного пункта рисует сама панель: отдельный виджет
        # приходилось двигать целыми пикселями и перерисовывать вместе с
        # куском кнопки под ним, отчего движение выходило дёрганым.
        self._nav_slide = QPropertyAnimation(sidebar, b"mark_y", self)
        self._nav_slide.setEasingCurve(QEasingCurve.Type.InOutCubic)

        layout.addStretch(1)

        self._sidebar_state = QLabel("")
        self._sidebar_state.setObjectName("SidebarVersion")
        self._sidebar_state.setWordWrap(True)
        layout.addWidget(self._sidebar_state)

        # Прокси — вторая включаемая вещь в программе, и состояние у него
        # своё: обход может работать, а Telegram при этом молчать.
        self._sidebar_proxy = QLabel("")
        self._sidebar_proxy.setObjectName("SidebarVersion")
        self._sidebar_proxy.setWordWrap(True)
        layout.addWidget(self._sidebar_proxy)

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
        self._mini.section_requested.connect(self.navigate)
        self._mini.install_core_requested.connect(self._install_core)
        self._mini.install_proxy_requested.connect(self._install_proxy)
        self.views["dashboard"].install_core_requested.connect(self._install_core)
        self.views["dashboard"].install_proxy_requested.connect(self._install_proxy)
        self.views["dashboard"].check_updates_requested.connect(self._check_updates_manually)
        self.views["updates"].whats_new_requested.connect(self._open_whats_new)
        self.views["updates"].something_updated.connect(self._recheck_after_install)
        self.views["telegram"].something_updated.connect(self._recheck_after_install)
        self.views["updates"].ignored_changed.connect(self._show_reminder)
        self.views["updates"].update_policy_changed.connect(self._recheck_after_install)
        self.views["updates"].auto_installed.connect(self._auto_installed)
        self.views["updates"].auto_failed.connect(self._auto_failed)
        self.views["settings"].tray_style_changed.connect(self._tray.refresh_style)
        self.controller.status_changed.connect(self.views["telegram"].on_status)

        # Разделы, где работа идёт долго, сами говорят о начале и конце.
        for key, title in BUSY_SECTIONS.items():
            self.views[key].busy_changed.connect(
                lambda busy, k=key, name=title: self.set_section_busy(k, name, busy)
            )
        self.controller.repair.running_changed.connect(
            lambda busy: self.set_section_busy("dashboard", "Починка", busy)
        )
        self.controller.foreign_conflict.connect(self._ask_about_foreign)
        self.controller.watch_alert.connect(self._watch_alert)
        self.controller.advice.connect(self._advice)
        # Тревога гаснет сама, когда очередная проверка прошла целиком.
        # Обновление при этом не трогаем: оно никуда не делось.
        self.controller.watch_calm.connect(lambda: self._tray.set_alert(False))

    # --- поведение ------------------------------------------------------

    def navigate(self, key: str) -> None:
        view = self.views.get(key)
        if view is None:
            return

        # Разделы в мини-окно не помещаются. Обзор — исключение: так программа
        # сама показывает себя при запуске, и окно из-за этого расти не должно.
        if self._compact and key != "dashboard":
            self.set_compact(False)

        self._stack.setCurrentWidget(view)
        self._current_section = key
        if button := self._nav_buttons.get(key):
            button.setChecked(True)
            self._move_nav_mark(button)

        # Экраны перечитывают данные при открытии: состояние сборки меняется
        # и снаружи приложения — через консольное меню или другой GUI.
        if reload_method := getattr(view, "reload", None):
            reload_method()
        if key == "logs":
            view.load_tail(self.controller.status.log_tail)

        # Проверка уже сходила на GitHub — незачем просить человека нажать
        # «Проверить» ради того же ответа. `reload` выше сбрасывает кнопки,
        # поэтому находку отдаём после него.
        if self._found_updates and (show := getattr(view, "show_known_updates", None)):
            show(self._found_updates)

    # --- долгая работа в разделах ----------------------------------------

    def set_section_busy(self, key: str, title: str, busy: bool) -> None:
        """Отмечает раздел занятым и сообщает, когда он освободился.

        Подбор идёт минутами, установка ядра — десятками секунд, и всё это
        время можно уйти на другую вкладку. Раньше о том, что работа
        закончилась, человек узнавал, только вернувшись обратно.
        """
        was_busy = key in self._busy_sections
        if busy:
            self._busy_sections[key] = title
        else:
            self._busy_sections.pop(key, None)

        if self._busy_sections and not self._spin_timer.isActive():
            self._spin_timer.start()
        elif not self._busy_sections:
            self._spin_timer.stop()
            self._spin_angle = 0

        self._draw_spinners()

        # Окно свёрнуто — человек его и не увидит, поэтому говорим в трей.
        # Проверять одну только видимость мало: свёрнутое в панель задач окно
        # Qt всё ещё считает видимым, и уведомление не приходило.
        if was_busy and not busy and (not self.isVisible() or self.isMinimized()):
            self._tray.showMessage(
                "ZapretXmel",
                f"{title}: работа закончена",
                build_icon(self.controller.status.is_active),
                6000,
            )

    def _move_nav_mark(self, button: QPushButton) -> None:
        """Ведёт полоску к выбранному пункту.

        Отсчёт от того места, где полоска сейчас, а не от прежнего пункта:
        по меню щёлкают быстро и подряд, и анимация, начинающая каждый раз
        с нуля, дёргала бы её назад перед каждым новым переходом.
        """
        self._sidebar.set_mark_height(button.height())
        target = float(button.y())
        current = self._sidebar.get_mark_y()

        if not self._nav_ready:
            self._nav_ready = True
            self._sidebar.set_mark_y(target)
            return

        if current == target:
            return

        self._nav_slide.stop()
        self._nav_slide.setDuration(motion.duration(NAV_SLIDE_MS))
        self._nav_slide.setStartValue(current)
        self._nav_slide.setEndValue(target)
        self._nav_slide.start()

    def _spin(self) -> None:
        self._spin_angle = (self._spin_angle + SPINNER_STEP) % 360
        self._draw_spinners()

    def _draw_spinners(self) -> None:
        for key, button in self._nav_buttons.items():
            if key in self._busy_sections:
                # Выбранный пункт написан белым, невыбранные — серым.
                # Серый кружок на белой надписи читался как чужой.
                button.setIcon(spinner_icon(self._spin_angle, bright=button.isChecked()))
            else:
                button.setIcon(QIcon())

    def _watch_alert(self, message: str, switched: bool) -> None:
        """Показывает сообщение сторожа.

        И в окне, и в трее: окно может быть свёрнуто, а новость из тех, из-за
        которых человек и полезет в программу.
        """
        # Отметка на значке остаётся и после того, как уведомление погасло:
        # его показывают секунд пять, а обход всё это время не работает.
        self._tray.set_alert(True)
        self._show_toast(message, COLORS["warning"])
        self._tray.showMessage(
            "ZapretXmel",
            message,
            build_icon(self.controller.status.is_active),
            8000,
        )
        if switched:
            log.info("Сторож переключил стратегию: %s", message)

    def _advice(self, text: str) -> None:
        """Совет о лучшей стратегии: в окне и в трее, но без тревоги — ничего не сломалось."""
        self._show_toast(text, COLORS["text_dim"])
        if not self.isVisible() or self.isMinimized():
            self._tray.showMessage(
                "ZapretXmel", text, build_icon(self.controller.status.is_active), 10000
            )

    def _ask_about_foreign(self, path: str) -> None:
        """Спрашивает разрешение подвинуть другую установку zapret.

        Служба у неё и у нас одна и та же, так что включение обхода её
        пересоздаёт. Человек, который до этого пользовался zapret вручную,
        должен узнать об этом до, а не после.
        """
        switch = dialogs.confirm(
            self,
            "На компьютере уже есть zapret",
            f"Обходом сейчас управляет установка в {path}.",
            "Служба Windows у неё и у нас называется одинаково, поэтому включение "
            "обхода здесь пересоздаст её на нашу копию, а в режиме обычного "
            "процесса ещё и остановит её winws.\n\n"
            "Прежняя установка никуда не денется: её консольное меню сможет "
            "вернуть службу себе. Свои списки доменов стоит перенести заранее — "
            "в разделе «Списки» есть импорт из другой папки zapret.",
            action="Переключить на эту программу",
        )

        if switch:
            self.controller.start(replace_foreign=True)

    def _install_core(self) -> None:
        """Ставит ядро по нажатию главной кнопки, когда его ещё нет."""
        self.navigate("updates")
        self.views["updates"].install_core()

    def _install_proxy(self) -> None:
        """То же для прокси: согласие уже получено, остаётся показать загрузку."""
        self.navigate("telegram")
        self.views["telegram"].install_proxy()

    def _first_run(self) -> None:
        status = self.controller.refresh()
        self.navigate("dashboard")

        if not self.settings.first_run_done:
            self.show_welcome()
            return

        if self.isVisible():
            self._show_whats_new()
        else:
            self._whats_new_pending = True
            self._tell_about_silent_update()

        # Служба стартует вместе с Windows сама, поэтому включать нечего —
        # это нужно только режиму обычного процесса. После автообновления
        # прежний экземпляр просит поднять то, что работало у него.
        resume_bypass = singleton.RESUME_BYPASS_FLAG in sys.argv
        resume_proxy = singleton.RESUME_PROXY_FLAG in sys.argv
        wanted_bypass = self.settings.start_bypass_on_launch or resume_bypass
        if wanted_bypass and status.core_present and not status.is_active:
            self._show_toast("Включаю обход…", COLORS["text_dim"])
            QTimer.singleShot(0, self.controller.start)

        # Прокси — дочерний процесс программы, своей службы у него нет.
        if (
            (self.settings.start_proxy_on_launch or resume_proxy)
            and status.telegram_installed
            and not status.telegram_running
        ):
            QTimer.singleShot(0, self.controller.toggle_telegram)

        self._look_for_updates()

    def _look_for_updates(self) -> None:
        """Проверяет обновления в фоне, через минуту после запуска.

        Сразу — нельзя: при старте программа и так опрашивает службу, читает
        ядро и, если попросили, поднимает обход. Задержка нужна и по смыслу:
        сообщение о новой версии в первую секунду перебивает то, ради чего
        программу открыли.
        """
        QTimer.singleShot(UPDATE_CHECK_DELAY_MS, self._check_updates_now)
        self._updates_timer.start(UPDATE_CHECK_INTERVAL_MS)

    def _check_updates_manually(self) -> None:
        """Проверка по кнопке: идёт даже с выключенными напоминаниями.

        Человек нажал сам — значит хочет ответа, в том числе «всё свежее»,
        которое при фоновой проверке мы намеренно не показываем.
        """
        self._updates_manual = True
        self._show_toast("Спрашиваю GitHub о новых версиях…", COLORS["text_dim"])
        self._start_update_check()

    def _check_updates_now(self) -> None:
        # Отдельной галочки «проверять» нет: если не напоминать ни о чём, то и
        # на GitHub без спроса не ходим. Так программа молчит в сети для тех,
        # кому это важно, а прежняя галочка в настройках не нужна.
        if updates.everything_ignored(self.settings.ignored_updates):
            return
        self._start_update_check()

    def _start_update_check(self) -> None:
        if self._updates_task is not None and self._updates_task.isRunning():
            return

        self._updates_task = Task(updates.check_all, self.settings.testing_builds)
        self._updates_task.done.connect(self._updates_found)
        self._updates_task.failed.connect(self._updates_failed)
        self._updates_task.start()

    def _recheck_after_install(self) -> None:
        """Перепроверяет обновления после установки чего-то из них.

        Без этого полоса, подсветка «Обновлений» и отметка в трее держались
        до следующей плановой проверки — то есть до двух часов после того,
        как обновляться стало не на что.
        """
        self._updates_quiet = True
        self._start_update_check()

    def _updates_failed(self, message: str) -> None:
        self._updates_quiet = False
        if self._updates_manual:
            self._updates_manual = False
            self._show_toast(f"Не удалось проверить: {message}", COLORS["danger"])

    def _updates_found(self, found: list) -> None:
        # Звать обновиться на то, что уже поставлено и ждёт запуска, — врать.
        found = [
            item
            for item in found
            if not (item.what == updates.APP and item.latest == self._staged_app)
        ]
        manual, self._updates_manual = self._updates_manual, False
        quiet, self._updates_quiet = self._updates_quiet, False
        ignored = self.settings.ignored_updates
        fresh = updates.without_ignored(updates.news(found, self._found_updates), ignored)
        self._found_updates = found

        self.views["updates"].set_pending(found)
        shown = self._show_reminder()
        self._auto_update()

        if not shown:
            # При фоновой проверке молчим: «всё свежее» — не новость. А вот на
            # прямой вопрос отвечать «последние версии» при отмеченной галочке
            # нельзя: это неправда.
            if manual and found:
                names = ", ".join(item.what for item in found)
                self._show_toast(
                    f"Есть обновления, напоминания выключены: {names}", COLORS["text_dim"]
                )
            elif manual:
                self._show_toast("Установлены последние версии", COLORS["success"])
            return

        # После установки остальное уже видели в разделе: полосу, которую
        # закрыли, обратно не выставляем и в трей не пишем — если только не
        # появилось что-то новое.
        if quiet and not fresh and not manual:
            return

        text = updates.summary(shown)
        self._update_banner.show()

        self._tray.showMessage(
            "ZapretXmel",
            text,
            build_icon(self.controller.status.is_active),
            6000,
        )

    # --- автообновление ---------------------------------------------------

    def _program_idle(self) -> bool:
        """Ничем ли не занята программа: ни подбор, ни починка, ни установка.

        Обновление ядра выключает обход, а обновление самой программы может
        перезапустить её. Посреди подбора стратегии это обрывает работу, ради
        которой человек ждал несколько минут.
        """
        return not self._busy_sections and not self.controller._busy

    def _auto_update(self) -> None:
        """Ставит следующую находку, если автообновление включено.

        По одной за раз: окончание установки ядра или прокси само запускает
        перепроверку, а она приводит сюда за следующей.
        """
        if not self.settings.auto_update:
            return

        due = updates.auto_candidates(
            self._found_updates, self.settings.ignored_updates, self._auto_done
        )
        if not due:
            return

        view = self.views["updates"]
        if not self._program_idle() or view.auto_busy():
            QTimer.singleShot(AUTO_UPDATE_RETRY_MS, self._auto_update)
            return

        item = due[0]
        log.info("Автообновление: ставлю %s", item.label)
        if not view.auto_install(item):
            QTimer.singleShot(AUTO_UPDATE_RETRY_MS, self._auto_update)

    def _notify(self, text: str) -> None:
        """Уведомление в углу экрана — единственное, что видно при автообновлении."""
        self._tray.showMessage(
            "ZapretXmel", text, build_icon(self.controller.status.is_active), 8000
        )

    def _auto_installed(self, what: str, version: str) -> None:
        self._auto_done.add((what, version))
        log.info("Автообновление: %s %s поставлено", what, version)

        if what != updates.APP:
            self._notify(
                f"Обновлено автоматически: {what} {version}. "
                "Что изменилось — в разделе «Обновления»."
            )
            return

        self._staged_app = version
        self._show_reminder_without_app()

        # Новая сборка уже на месте старой. Работающий экземпляр остаётся
        # прежним, и сам он не перезапускается, пока человек может им
        # пользоваться: закрыть окно у него из-под рук хуже, чем подождать.
        if self._can_restart_quietly():
            self._restart_quietly(version)
            return

        self._notify(
            f"Программа обновлена до {version}. Новая версия запустится при "
            "следующем запуске, список изменений покажется сам."
        )

    def _show_reminder_without_app(self) -> None:
        """Снимает напоминание о программе, которая уже поставлена."""
        self._found_updates = [
            item for item in self._found_updates if item.what != updates.APP
        ]
        self.views["updates"].set_pending(self._found_updates)
        self._show_reminder()

    def _auto_failed(self, what: str, message: str) -> None:
        # Неудачную версию за этот запуск больше не берём: иначе та же ошибка
        # повторялась бы каждые пять минут.
        failed = next(
            (item for item in self._found_updates if item.what == what), None
        )
        if failed is not None:
            self._auto_done.add((what, failed.latest))
        log.warning("Автообновление: %s не поставилось: %s", what, message)
        self._notify(f"Не удалось обновить {what}: {message}")

    def _can_restart_quietly(self) -> bool:
        """Можно ли перезапуститься прямо сейчас, никому не помешав.

        Только когда окно спрятано в трей, ничего не идёт и не работает профиль
        приложения: профили поднимаются по своим правилам, и восстанавливать их
        за человека мы не возьмёмся.
        """
        return (
            not self.isVisible()
            and self._program_idle()
            and not self.controller._alive_profiles()
        )

    def _restart_quietly(self, version: str) -> None:
        """Перезапускает обновлённую программу в трей, с тем же обходом и прокси."""
        status = self.controller.status
        extra = [singleton.TRAY_FLAG]
        # Служба живёт без программы, а обычный процесс и прокси — нет.
        if status.is_active and self.settings.run_mode != "service":
            extra.append(singleton.RESUME_BYPASS_FLAG)
        if status.telegram_running:
            extra.append(singleton.RESUME_PROXY_FLAG)

        log.info("Автообновление: перезапускаюсь в версию %s (%s)", version, " ".join(extra))
        try:
            selfupdate.restart(extra)
        except selfupdate.SelfUpdateError as error:
            self._notify(
                f"Программа обновлена до {version}, но перезапуститься не вышло: {error}. "
                "Новая версия запустится при следующем запуске."
            )
            return
        self.quit()

    def _tell_about_silent_update(self) -> None:
        """Говорит в углу экрана, что программа обновилась, пока окно спрятано."""
        seen = self.settings.last_seen_version
        if not seen or seen == __version__:
            return
        self._notify(
            f"Программа обновилась до {__version__}. Что изменилось — "
            "покажу, когда откроете окно."
        )

    def _show_reminder(self) -> list:
        """Приводит полосу, пункт меню и трей к находке и галочкам.

        Галочку можно переключить и между проверками, поэтому ни GitHub, ни
        уведомление здесь не нужны.
        """
        shown = updates.without_ignored(self._found_updates, self.settings.ignored_updates)

        # Тревогу сторожа отметка об обновлении не перебивает — об этом
        # заботится сам трей. Здесь важно, что пустая проверка её снимает:
        # обновиться могли и мимо полосы, прямо в разделе.
        self._tray.set_update(bool(shown))

        if not shown:
            # Полосу надо убрать: обновиться могли и мимо неё — например,
            # поставить новое ядро в разделе «Обновления». Висящее после
            # этого «доступна новая версия» просто врёт.
            self._hide_update_banner()
            self._mini.set_update_available(False)
            return shown

        self._mini.set_update_available(True)
        self._update_text.setText(updates.summary(shown))
        # Пункт меню подсвечивается: человек может закрыть полосу, но
        # напоминание должно остаться там, куда он за обновлением пойдёт.
        self._mark_updates_nav(True)
        return shown

    def _open_whats_new(self) -> None:
        """Открывает окно по кнопке — независимо от того, видели его или нет."""
        entries = changelog.history(__version__)
        if not entries:
            self._show_toast(
                f"Для версии {__version__} описания изменений нет", COLORS["text_muted"]
            )
            return

        self._whats_new = whatsnew.WhatsNewWindow(entries, f"Версия {__version__}", parent=self)
        self._whats_new.show()
        foreground.force(int(self._whats_new.winId()))

    def _show_whats_new(self) -> None:
        """Рассказывает об изменениях — один раз после обновления.

        При первом запуске молчим: человеку нечего сравнивать, а окно
        знакомства важнее.
        """
        seen = self.settings.last_seen_version
        if seen == __version__:
            return

        show = whatsnew.should_show(seen, __version__, self.settings.first_run_done)
        self.settings.last_seen_version = __version__
        self.settings.save()

        if not show:
            return

        entries = changelog.since(seen, __version__)
        if not entries:
            log.info("Нет описания изменений для версии %s", __version__)
            return

        self._whats_new = whatsnew.WhatsNewWindow(
            entries,
            f"Обновились до {__version__}",
            whatsnew.skipped_text(seen, entries),
            parent=self,
        )
        self._whats_new.show()
        foreground.force(int(self._whats_new.winId()))

    def _repair_from_welcome(self) -> None:
        self.navigate("dashboard")
        self.controller.repair.start()

    def show_welcome(self) -> None:
        """Открывает знакомство — при первом запуске и по кнопке из настроек."""
        self._welcome = WelcomeWindow(self.controller, self)
        self._welcome.navigate.connect(self.navigate)
        self._welcome.repair_requested.connect(self._repair_from_welcome)
        self._welcome.tray_style_changed.connect(self._tray.refresh_style)
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

        if not status.telegram_installed:
            self._sidebar_proxy.setText("прокси Telegram не установлен")
            colour = COLORS["text_muted"]
        elif status.telegram_running:
            self._sidebar_proxy.setText("прокси Telegram работает")
            colour = BRAND["telegram"]
        else:
            self._sidebar_proxy.setText("прокси Telegram выключен")
            colour = COLORS["text_muted"]

        self._sidebar_proxy.setStyleSheet(f"color: {colour}; padding: 0 {SPACE['lg']}px;")

    def _show_toast(self, text: str, color: str) -> None:
        for label in (self._toast, self._mini.toast):
            label.setText(text)
            label.setStyleSheet(f"color: {color};")
        QTimer.singleShot(TOAST_MS, lambda: self._clear_toast(text))

    def _clear_toast(self, text: str) -> None:
        for label in (self._toast, self._mini.toast):
            if label.text() == text:
                label.setText("")

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

        if self._whats_new_pending:
            self._whats_new_pending = False
            self._show_whats_new()

    def showEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        """Пересчитывает полоску меню, когда окно наконец показали.

        При запуске свёрнутым в трей разметки ещё нет: кнопки не имеют
        размеров, и полоска получала высоту всего списка. Так она и
        оставалась после разворачивания.
        """
        super().showEvent(event)
        self._nav_ready = False
        self._current_section = "dashboard"
        if button := self._nav_buttons.get(self._current_section):
            QTimer.singleShot(0, lambda: self._move_nav_mark(button))

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

        self._activation.stop()
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

