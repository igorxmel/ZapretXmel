"""Главное окно: боковое меню и переключение экранов."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
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
from app.core import foreground, updates
from app.core.config import Settings
from app.ui import dialogs, motion
from app.ui.activation import ActivationListener
from app.ui.controller import Controller, Status
from app.ui.frameless import FramelessWindow
from app.ui.theme.tokens import BRAND, COLORS, SIZE, SPACE
from app.ui.tray import Tray, app_icon, build_icon
from app.ui.views import whatsnew
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
        self._updates_manual = False
        # Последняя находка: её отдают экранам, чтобы те не спрашивали
        # GitHub о том же самом второй раз.
        self._found_updates: list = []
        self._nav_ready = False
        self._current_section = "dashboard"
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

        # Повторный запуск не открывает второе окно, а просит это, — и показывать
        # его надлежит самому окну, иначе свёрнутое в трей не оживает (см. activation.py).
        self._activation = ActivationListener(self)
        self._activation.activated.connect(self.present)
        self._activation.start()

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

    def _hide_update_banner(self) -> None:
        """Убирает полосу вместе с подсветкой пункта меню.

        Кнопка «✕» на полосе этого не делает нарочно: человек отложил
        обновление, а не сделал его. Здесь другое — обновляться больше не
        на что.
        """
        self._update_banner.hide()
        if button := self._nav_buttons.get("updates"):
            button.setProperty("alert", False)
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

        entries = (
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
        self._nav_buttons: dict[str, QPushButton] = {}

        # Кнопки отступают от левого края ровно на ширину полоски: рисует её
        # сама панель, а дочерние виджеты всегда ложатся поверх родителя —
        # без этой полосы кнопка закрывала бы её целиком.
        nav = QVBoxLayout()
        nav.setContentsMargins(round(NAV_MARK_WIDTH), 0, 0, 0)
        nav.setSpacing(0)
        layout.addLayout(nav)

        for key, title in entries:
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
        self.views["dashboard"].install_core_requested.connect(self._install_core)
        self.views["dashboard"].install_proxy_requested.connect(self._install_proxy)
        self.views["dashboard"].check_updates_requested.connect(self._check_updates_manually)
        self.views["updates"].whats_new_requested.connect(self._open_whats_new)
        self.views["updates"].something_updated.connect(self._start_update_check)
        self.views["settings"].tray_style_changed.connect(self._tray.refresh_style)
        self.controller.status_changed.connect(self.views["telegram"].on_status)

        # Разделы, где работа идёт долго, сами говорят о начале и конце.
        for key, title in BUSY_SECTIONS.items():
            self.views[key].busy_changed.connect(
                lambda busy, k=key, name=title: self.set_section_busy(k, name, busy)
            )
        self.controller.foreign_conflict.connect(self._ask_about_foreign)
        self.controller.watch_alert.connect(self._watch_alert)
        # Тревога гаснет сама, когда очередная проверка прошла целиком.
        # Обновление при этом не трогаем: оно никуда не делось.
        self.controller.watch_calm.connect(lambda: self._tray.set_alert(False))

    # --- поведение ------------------------------------------------------

    def navigate(self, key: str) -> None:
        view = self.views.get(key)
        if view is None:
            return

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

        self._show_whats_new()

        # Служба стартует вместе с Windows сама, поэтому включать нечего —
        # это нужно только режиму обычного процесса.
        if self.settings.start_bypass_on_launch and status.core_present and not status.is_active:
            self._show_toast("Включаю обход…", COLORS["text_dim"])
            QTimer.singleShot(0, self.controller.start)

        # Прокси — дочерний процесс программы, своей службы у него нет.
        if (
            self.settings.start_proxy_on_launch
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
        if not self.settings.notify_updates:
            return

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
        if not self.settings.notify_updates:
            return
        self._start_update_check()

    def _start_update_check(self) -> None:
        if self._updates_task is not None and self._updates_task.isRunning():
            return

        self._updates_task = Task(updates.check_all, self.settings.testing_builds)
        self._updates_task.done.connect(self._updates_found)
        self._updates_task.failed.connect(self._updates_failed)
        self._updates_task.start()

    def _updates_failed(self, message: str) -> None:
        if self._updates_manual:
            self._updates_manual = False
            self._show_toast(f"Не удалось проверить: {message}", COLORS["danger"])

    def _updates_found(self, found: list) -> None:
        manual, self._updates_manual = self._updates_manual, False
        self._found_updates = found

        # Тревогу сторожа отметка об обновлении не перебивает — об этом
        # заботится сам трей. Здесь важно, что пустая проверка её снимает:
        # обновиться могли и мимо полосы, прямо в разделе.
        self._tray.set_update(bool(found))

        if not found:
            # Полосу надо убрать: обновиться могли и мимо неё — например,
            # поставить новое ядро в разделе «Обновления». Висящее после
            # этого «доступна новая версия» просто врёт.
            self._hide_update_banner()
            # При фоновой проверке молчим: «всё свежее» — не новость.
            if manual:
                self._show_toast("Установлены последние версии", COLORS["success"])
            return

        text = updates.summary(found)

        self._update_text.setText(text)
        self._update_banner.show()

        # Пункт меню подсвечивается: человек может закрыть полосу, но
        # напоминание должно остаться там, куда он за обновлением пойдёт.
        if button := self._nav_buttons.get("updates"):
            button.setProperty("alert", True)
            button.style().unpolish(button)
            button.style().polish(button)

        self._tray.showMessage(
            "ZapretXmel",
            text,
            build_icon(self.controller.status.is_active),
            6000,
        )

    def _open_whats_new(self) -> None:
        """Открывает окно по кнопке — независимо от того, видели его или нет."""
        notes = whatsnew.notes_for_current_version()
        if not notes:
            self._show_toast(
                f"Для версии {__version__} описания изменений нет", COLORS["text_muted"]
            )
            return

        self._whats_new = whatsnew.WhatsNewWindow(notes, self)
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

        notes = whatsnew.notes_for_current_version()
        if not notes:
            log.info("Нет описания изменений для версии %s", __version__)
            return

        self._whats_new = whatsnew.WhatsNewWindow(notes, self)
        self._whats_new.show()
        foreground.force(int(self._whats_new.winId()))

    def show_welcome(self) -> None:
        """Открывает знакомство — при первом запуске и по кнопке из настроек."""
        self._welcome = WelcomeWindow(self.controller, self)
        self._welcome.navigate.connect(self.navigate)
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

