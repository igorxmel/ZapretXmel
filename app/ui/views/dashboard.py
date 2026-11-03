"""Главный экран: включение обхода и общее состояние."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core import service
from app.ui.controller import Controller, Status
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.views.controls import PowerPair, QuickPanel, StatusNotices
from app.ui.widgets import Card, Divider, KeyValueRow, StatusPill, view_header


class DashboardView(QWidget):
    """Две кнопки и ответ на вопрос «работает ли сейчас обход»."""

    navigate = pyqtSignal(str)
    install_core_requested = pyqtSignal()
    install_proxy_requested = pyqtSignal()
    check_updates_requested = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Обзор высокий. Без прокрутки на ноутбуке с увеличением экрана (1920×1080 при
        # 150%) его низ обрезался, а окно не могло стать меньше содержимого и
        # вырастало за край экрана.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        scroll.setWidget(content)

        layout.addWidget(view_header("Обзор", "Состояние обхода блокировок и быстрые действия"))

        self._notices = StatusNotices()
        layout.addWidget(self._notices)

        layout.addWidget(self._build_power_card())

        details = QHBoxLayout()
        details.setSpacing(SPACE["lg"])
        details.addWidget(self._build_status_card(), 1)
        details.addWidget(self._build_actions_card(), 1)
        layout.addLayout(details)
        layout.addStretch(1)

        controller.status_changed.connect(self.apply_status)

    # --- сборка интерфейса ---------------------------------------------

    def _build_power_card(self) -> Card:
        card = Card()
        body = card.body()
        body.setSpacing(SPACE["md"])

        self._power = PowerPair(self.controller, spacing=SPACE["xxl"])
        self._power.install_core_requested.connect(self.install_core_requested)
        self._power.install_proxy_requested.connect(self.install_proxy_requested)
        body.addWidget(self._power)

        return card

    def _build_status_card(self) -> Card:
        card = Card("Состояние")
        body = card.body()

        self._pill_service = StatusPill("служба", COLORS["text_muted"])
        self._pill_process = StatusPill("winws", COLORS["text_muted"])
        # «winws: 1» само по себе человеку ничего не говорит: он не обязан
        # знать, что это за процесс и почему их может быть несколько.
        self._pill_process.setToolTip(
            "winws — программа из сборки zapret, которая и делает обход: она "
            "перехватывает пакеты и меняет их так, чтобы фильтр провайдера не "
            "понял, куда вы идёте.\n\nЦифра — сколько таких процессов "
            "работает. Обычно один; второй появляется, когда включён профиль "
            "приложения."
        )
        pills = QHBoxLayout()
        pills.setSpacing(SPACE["lg"])
        pills.addWidget(self._pill_service)
        pills.addWidget(self._pill_process)
        pills.addStretch(1)
        body.addLayout(pills)

        self._row_core = KeyValueRow("Версия ядра")
        self._row_mode = KeyValueRow("Режим запуска")
        self._row_strategies = KeyValueRow("Стратегий доступно")

        # Прокси — вторая включаемая вещь, и у неё своё состояние: он может
        # работать, но не быть прописанным в самом Telegram, и тогда толку
        # от него никакого.
        self._row_proxy = KeyValueRow("Прокси для Telegram")
        self._row_proxy.setToolTip(
            "Поднять прокси мало — его ещё нужно добавить в настройках "
            "Telegram. Кнопка «Открыть в Telegram» на вкладке Telegram "
            "делает это за вас."
        )

        # Чтобы не гадали на программу, когда лежит интернет.
        self._row_network = KeyValueRow("Сеть")
        self._row_network.setToolTip(
            "Поднят ли сетевой адаптер. Работает ли интернет на самом деле, "
            "показывает кнопка «Проверить, работает ли сейчас»."
        )

        for row in (
            self._row_core,
            self._row_mode,
            self._row_strategies,
            self._row_proxy,
            self._row_network,
        ):
            body.addWidget(row)

        body.addStretch(1)
        return card

    def _build_actions_card(self) -> Card:
        card = Card("Быстрые действия")
        body = card.body()

        self._panel = QuickPanel(self.controller)
        body.addWidget(self._panel)

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

    def reload(self) -> None:
        self._panel.reload()

    def apply_status(self, status: Status) -> None:
        self._panel.apply_status(status)
        self._notices.apply_status(status)
        self._power.apply_status(status)

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
        self._row_proxy.set_value(self._proxy_state(status))
        self._row_network.set_value(status.network_label or "—")

    @staticmethod
    def _proxy_state(status: Status) -> str:
        """Состояние прокси одной строкой — от «нет» до «им пользуются»."""
        if not status.telegram_installed:
            return "не установлен"

        version = status.telegram_version or "версия неизвестна"
        if not status.telegram_running:
            return f"остановлен · {version}"
        if status.telegram_connected:
            return f"работает, Telegram подключён · {version}"
        return f"работает, но не добавлен в Telegram · {version}"
