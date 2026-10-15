"""Главный экран: включение обхода и общее состояние."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.core import service
from app.ui.controller import Controller, Status
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, KeyValueRow, PowerButton, StatusPill, view_header


class PowerTile(QWidget):
    """Круглый выключатель с подписью — одна управляемая штука."""

    toggled = pyqtSignal()

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.button = PowerButton()
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
        self.button.setEnabled(enabled)
        self._state.setText(state)


class DashboardView(QWidget):
    """Две кнопки и ответ на вопрос «работает ли сейчас обход»."""

    navigate = pyqtSignal(str)
    install_core_requested = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])

        layout.addWidget(view_header("Обзор", "Состояние обхода блокировок и быстрые действия"))

        self._vpn_banner = QLabel("")
        self._vpn_banner.setObjectName("Dim")
        self._vpn_banner.setWordWrap(True)
        self._vpn_banner.hide()
        layout.addWidget(self._vpn_banner)

        layout.addWidget(self._build_power_card())

        details = QHBoxLayout()
        details.setSpacing(SPACE["lg"])
        details.addWidget(self._build_status_card(), 1)
        details.addWidget(self._build_actions_card(), 1)
        layout.addLayout(details)
        layout.addStretch(1)

        controller.status_changed.connect(self.apply_status)
        controller.busy_changed.connect(self._bypass.button.set_busy)

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

        self._telegram = PowerTile("Telegram")
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

        actions = (
            ("Подобрать стратегию автоматически", "autopick"),
            ("Выбрать стратегию вручную", "strategies"),
            ("Проверить систему", "diagnostics"),
            ("Обновить ядро", "updates"),
        )
        for title, destination in actions:
            button = QPushButton(title)
            button.clicked.connect(lambda _, target=destination: self.navigate.emit(target))
            body.addWidget(button)

        body.addStretch(1)
        return card

    # --- обновление состояния -------------------------------------------

    def _toggle_bypass(self) -> None:
        # Без ядра включать нечего, но и гасить кнопку неправильно: человек
        # жмёт главную кнопку программы и не получает ничего, даже объяснения.
        # Поэтому первое нажатие ставит ядро — ровно как у кнопки Telegram.
        if not self.controller.status.core_present:
            self.install_core_requested.emit()
            return
        self.controller.toggle()

    def _toggle_telegram(self) -> None:
        if not self.controller.status.telegram_installed:
            self.navigate.emit("telegram")
            return
        self.controller.toggle_telegram()

    def apply_status(self, status: Status) -> None:
        if status.active_vpn:
            self._vpn_banner.setText(
                f"Трафик идёт через {status.active_vpn}. Пока туннель включён, обход ни на что "
                "не влияет, а проверки измеряют VPN — выключите его перед подбором стратегии."
            )
            self._vpn_banner.setStyleSheet(f"color: {COLORS['warning']};")
            self._vpn_banner.show()
        else:
            self._vpn_banner.hide()

        self._bypass.apply(
            active=status.is_active,
            enabled=True,
            state=self._bypass_state(status),
        )

        # Кнопка Telegram остаётся нажимаемой и без прокси: щелчок отправляет
        # на его экран, где он ставится, — иначе непонятно, что делать дальше.
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
