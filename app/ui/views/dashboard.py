"""Главный экран: включение обхода и общее состояние."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import service, strategies
from app.ui import dialogs
from app.ui.controller import Controller, Status
from app.ui.theme.tokens import BRAND, COLORS, SPACE
from app.ui.widgets import Card, Divider, KeyValueRow, PowerButton, StatusPill, view_header
from app.ui.workers import QuickCheckWorker


class PowerTile(QWidget):
    """Круглый выключатель с подписью — одна управляемая штука."""

    toggled = pyqtSignal()

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        accent: str = COLORS["success"],
    ):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.button = PowerButton(accent=accent)
        self.button.clicked.connect(self.toggled.emit)
        layout.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._title = QLabel(title)
        self._title.setObjectName("ViewTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._title)

        self._state = QLabel("")
        self._state.setObjectName("Dim")
        self._state.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._state.setWordWrap(True)
        layout.addWidget(self._state)

    def apply(self, active: bool, enabled: bool, state: str) -> None:
        self.button.setChecked(active)
        self.button.set_available(enabled)
        self._state.setText(state)


class DashboardView(QWidget):
    """Две кнопки и ответ на вопрос «работает ли сейчас обход»."""

    navigate = pyqtSignal(str)
    install_core_requested = pyqtSignal()
    install_proxy_requested = pyqtSignal()
    check_updates_requested = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._quick: QuickCheckWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])

        layout.addWidget(view_header("Обзор", "Состояние обхода блокировок и быстрые действия"))

        self._vpn_banner = QLabel("")
        self._vpn_banner.setObjectName("Dim")
        self._vpn_banner.setWordWrap(True)
        self._vpn_banner.hide()
        layout.addWidget(self._vpn_banner)

        # Чужая установка zapret пользуется той же службой, поэтому состояние
        # ниже относится к ней, а не к нам. Промолчать об этом нельзя.
        self._foreign_banner = QLabel("")
        self._foreign_banner.setObjectName("Dim")
        self._foreign_banner.setWordWrap(True)
        self._foreign_banner.hide()
        layout.addWidget(self._foreign_banner)

        layout.addWidget(self._build_power_card())

        details = QHBoxLayout()
        details.setSpacing(SPACE["lg"])
        details.addWidget(self._build_status_card(), 1)
        details.addWidget(self._build_actions_card(), 1)
        layout.addLayout(details)
        layout.addStretch(1)

        controller.status_changed.connect(self.apply_status)
        controller.busy_changed.connect(self._bypass.button.set_busy)
        controller.telegram_busy.connect(self._telegram.button.set_busy)

    # --- сборка интерфейса ---------------------------------------------

    def _build_power_card(self) -> Card:
        card = Card()
        body = card.body()
        body.setSpacing(SPACE["md"])

        tiles = QHBoxLayout()
        tiles.setSpacing(SPACE["xxl"])
        tiles.addStretch(1)

        self._bypass = PowerTile("Обход блокировок")
        self._bypass.toggled.connect(self._toggle_bypass)
        tiles.addWidget(self._bypass)

        # Прокси везде обозначен голубым — в трее, в боковом меню. Зелёное
        # кольцо здесь выбивалось из этого ряда.
        self._telegram = PowerTile("Telegram", accent=BRAND["telegram"])
        self._telegram.toggled.connect(self._toggle_telegram)
        tiles.addWidget(self._telegram)

        tiles.addStretch(1)
        body.addLayout(tiles)

        return card

    def _build_status_card(self) -> Card:
        card = Card("Состояние")
        body = card.body()

        self._pill_service = StatusPill("служба", COLORS["text_muted"])
        self._pill_process = StatusPill("winws", COLORS["text_muted"])
        pills = QHBoxLayout()
        pills.setSpacing(SPACE["lg"])
        pills.addWidget(self._pill_service)
        pills.addWidget(self._pill_process)
        pills.addStretch(1)
        body.addLayout(pills)

        self._row_core = KeyValueRow("Версия ядра")
        self._row_mode = KeyValueRow("Режим запуска")
        self._row_strategies = KeyValueRow("Стратегий доступно")
        for row in (self._row_core, self._row_mode, self._row_strategies):
            body.addWidget(row)

        body.addStretch(1)
        return card

    def _build_actions_card(self) -> Card:
        card = Card("Быстрые действия")
        body = card.body()

        # Главный вопрос человека, включившего обход, — «ну и работает ли?».
        # Подбор отвечает на него за минуты, диагностика проверяет систему, а
        # не сервисы; здесь — ответ за несколько секунд.
        self._check_button = QPushButton("Проверить, работает ли сейчас")
        self._check_button.clicked.connect(self._run_quick_check)
        body.addWidget(self._check_button)

        self._check_result = QLabel("")
        self._check_result.setObjectName("Dim")
        self._check_result.setWordWrap(True)
        body.addWidget(self._check_result)

        # Сторож проверяет сам, и об этом стоит знать, не нажимая ничего.
        self._watch_line = QLabel("")
        self._watch_line.setWordWrap(True)
        body.addWidget(self._watch_line)

        body.addWidget(Divider())

        # Смена стратегии — единственное, за чем сюда возвращаются чаще
        # всего. Раньше ради неё приходилось уходить на другой экран, хотя
        # всё, что нужно, — выбрать из списка и нажать.
        body.addWidget(QLabel("Стратегия обхода"))

        self._strategy_box = QComboBox()
        body.addWidget(self._strategy_box)

        # Называем делом, а не намерением: рядом на экране «Стратегии» стоит
        # «Применить и включить», и разница между двумя «Применить» была
        # загадкой — на самом деле её нет.
        self._apply_button = QPushButton("Применить и включить")
        self._apply_button.clicked.connect(self._apply_strategy)
        body.addWidget(self._apply_button)

        body.addWidget(Divider())

        # Единственная оставшаяся ссылка: подбор — это не действие на один
        # щелчок, у него свой экран с выбором сервисов и таблицей.
        autopick = QPushButton("Подобрать стратегию автоматически")
        autopick.clicked.connect(lambda: self.navigate.emit("autopick"))
        body.addWidget(autopick)

        updates_button = QPushButton("Проверить обновления")
        updates_button.setToolTip(
            "Программа, ядро zapret и прокси для Telegram. Сама она спрашивает "
            "об этом раз в шесть часов"
        )
        updates_button.clicked.connect(self.check_updates_requested.emit)
        body.addWidget(updates_button)

        body.addStretch(1)
        return card

    def _say_watch(self) -> None:
        """Строка о последней проверке — своей или сторожевой."""
        when = self.controller.last_check_at
        check = self.controller.last_check
        if when is None or check is None:
            self._watch_line.setText("Проверки ещё не было")
            self._watch_line.setStyleSheet(f"color: {COLORS['text_muted']};")
            return

        minutes = int((datetime.now() - when).total_seconds() // 60)
        if minutes < 1:
            ago = "только что"
        elif minutes < 60:
            ago = f"{minutes} мин назад"
        else:
            ago = f"{minutes // 60} ч назад"

        if check.everything_works:
            self._watch_line.setText(f"Проверено {ago}: всё работало")
            self._watch_line.setStyleSheet(f"color: {COLORS['success']};")
        elif check.working:
            self._watch_line.setText(f"Проверено {ago}: не работает {", ".join(check.broken)}")
            self._watch_line.setStyleSheet(f"color: {COLORS['warning']};")
        else:
            self._watch_line.setText(f"Проверено {ago}: не работало ничего")
            self._watch_line.setStyleSheet(f"color: {COLORS['danger']};")

    def _fill_strategies(self) -> None:
        """Заполняет список: избранные наверх, выбранная — текущей.

        Показывается именно выбранная программой стратегия, а не та, что
        осталась в списке с прошлого раза: подбор меняет выбор на своём
        экране, и на обзоре должна быть видна она же.
        """
        names = [spec.name for spec in strategies.load_all()]
        favorites = self.controller.settings.favorites
        names.sort(key=lambda name: name not in favorites)

        self._strategy_box.blockSignals(True)
        self._strategy_box.clear()
        for name in names:
            self._strategy_box.addItem(("★ " if name in favorites else "") + name, name)

        index = self._strategy_box.findData(self.controller.settings.selected_strategy)
        if index >= 0:
            self._strategy_box.setCurrentIndex(index)
        self._strategy_box.blockSignals(False)

        self._apply_button.setEnabled(bool(names))

    def _sync_strategy_box(self) -> None:
        """Подхватывает смену стратегии, сделанную на другом экране.

        Пока список раскрыт или в фокусе, не трогаем: человек выбирает, и
        подменять выбор под рукой нельзя.
        """
        if self._strategy_box.hasFocus() or self._strategy_box.view().isVisible():
            return

        wanted = self.controller.settings.selected_strategy
        if not wanted or self._strategy_box.currentData() == wanted:
            return

        index = self._strategy_box.findData(wanted)
        if index < 0:
            self._fill_strategies()
            return

        self._strategy_box.blockSignals(True)
        self._strategy_box.setCurrentIndex(index)
        self._strategy_box.blockSignals(False)

    def _apply_strategy(self) -> None:
        name = self._strategy_box.currentData()
        if not name:
            return

        self.controller.select_strategy(name)
        if self.controller.status.is_active:
            self.controller.restart()
        else:
            self.controller.start()

    # --- обновление состояния -------------------------------------------

    def _run_quick_check(self) -> None:
        if self._quick is not None and self._quick.isRunning():
            return

        self._check_button.setEnabled(False)
        self._say_check("Проверяю сервисы…", COLORS["text_muted"])

        settings = self.controller.settings
        self._quick = QuickCheckWorker(
            timeout=settings.probe_timeout, parallel=settings.probe_parallel
        )
        self._quick.done.connect(self._quick_done)
        self._quick.failed.connect(lambda text: self._say_check(text, COLORS["danger"]))
        self._quick.finished.connect(lambda: self._check_button.setEnabled(True))
        self._quick.start()

    def _quick_done(self, check) -> None:
        self.controller.remember_check(check)
        if check.everything_works:
            colour = COLORS["success"]
        elif check.working:
            colour = COLORS["warning"]
        else:
            colour = COLORS["danger"]

        self._say_check(check.verdict[:1].upper() + check.verdict[1:], colour)

    def _say_check(self, text: str, colour: str) -> None:
        self._check_result.setStyleSheet(f"color: {colour};")
        self._check_result.setText(text)

    def _toggle_bypass(self) -> None:
        if not self.controller.status.core_present:
            self._offer_install("core")
            return
        self.controller.toggle()

    def _toggle_telegram(self) -> None:
        if not self.controller.status.telegram_installed:
            self._offer_install("proxy")
            return
        self.controller.toggle_telegram()

    def _offer_install(self, what: str) -> None:
        """Предлагает поставить то, чего ещё нет, и ставит с согласия.

        Гасить кнопку неправильно: человек жмёт главную кнопку программы и
        не получает ничего, даже объяснения. Но и ставить молча нельзя —
        нажатие на «включить» уходило качать полтора мегабайта с GitHub и
        перекидывало в другой раздел, о чём никто не просил.

        Поэтому оба нажатия ведут себя одинаково: вопрос, а потом установка
        там, где видно загрузку. Раньше ядро ставилось само, а прокси просто
        открывал свой раздел, и почему кнопки работают по-разному, понять
        было нельзя.
        """
        offers = {
            "core": (
                "Ядро zapret не установлено",
                "Скачать и установить его сейчас?",
                "Это сборка Flowseal — около полутора мегабайт с GitHub. "
                "Без неё включать нечего: все стратегии лежат именно в ней.",
            ),
            "proxy": (
                "Прокси для Telegram не установлен",
                "Скачать и установить его сейчас?",
                "Это tg-ws-proxy — около двадцати мегабайт с GitHub. "
                "Telegram Desktop не чинится обычными стратегиями, для него "
                "нужен отдельный локальный прокси.",
            ),
        }
        title, question, details = offers[what]

        if not dialogs.confirm(
            self, title, question, details, action="Скачать и установить"
        ):
            return

        # Установка показывается там, где у неё есть полоса загрузки: файл
        # качается с GitHub, а он у части провайдеров открывается не сразу.
        if what == "core":
            self.install_core_requested.emit()
        else:
            self.install_proxy_requested.emit()

    def reload(self) -> None:
        self._fill_strategies()

    def apply_status(self, status: Status) -> None:
        self._say_watch()
        self._sync_strategy_box()
        if status.active_vpn:
            self._vpn_banner.setText(
                f"Трафик идёт через {status.active_vpn}. Пока туннель включён, обход ни на что "
                "не влияет, а проверки измеряют VPN — выключите его перед подбором стратегии."
            )
            self._vpn_banner.setStyleSheet(f"color: {COLORS['warning']};")
            self._vpn_banner.show()
        else:
            self._vpn_banner.hide()

        if status.foreign_install:
            self._foreign_banner.setText(
                f"На компьютере уже есть zapret: {status.foreign_install}. Служба у него и "
                "у нас одна и та же, поэтому состояние ниже относится к нему. Включение "
                "обхода здесь переключит службу на эту программу — она сначала спросит."
            )
            self._foreign_banner.setStyleSheet(f"color: {COLORS['warning']};")
            self._foreign_banner.show()
        else:
            self._foreign_banner.hide()

        self._bypass.apply(
            active=status.is_active,
            enabled=True,
            state=self._bypass_state(status),
        )

        # Кнопка Telegram остаётся нажимаемой и без прокси: щелчок предлагает
        # его поставить — иначе непонятно, что делать дальше.
        if status.telegram_running:
            telegram_state = "прокси работает"
        elif status.telegram_installed:
            telegram_state = "прокси остановлен"
        else:
            telegram_state = "нажмите, чтобы установить"

        self._telegram.apply(active=status.telegram_running, enabled=True, state=telegram_state)

        running = status.service_state == "running"
        self._pill_service.set_state(
            f"служба: {service.LABELS.get(status.service_state, status.service_state)}",
            COLORS["success"] if running else COLORS["text_muted"],
        )
        self._pill_process.set_state(
            f"winws: {status.winws_count}",
            COLORS["success"] if status.winws_count else COLORS["text_muted"],
        )

        self._row_core.set_value(status.core_version or "—")
        service_mode = self.controller.settings.run_mode == "service"
        self._row_mode.set_value("служба Windows" if service_mode else "обычный процесс")
        self._row_strategies.set_value(str(status.strategy_count))

    @staticmethod
    def _bypass_state(status: Status) -> str:
        if not status.core_present:
            return "нажмите, чтобы установить ядро"
        if status.active_strategy:
            return f"стратегия «{status.active_strategy}»"
        if status.selected_strategy:
            return f"выбрана «{status.selected_strategy}»"
        return "стратегия не выбрана"
