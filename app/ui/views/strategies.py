"""Экран выбора стратегии.

Список строится сканированием папки ядра, поэтому стратегии из нового релиза
Flowseal появляются здесь сами. Для каждой показывается разбор по секциям —
видно, какие порты и списки она затрагивает и каким способом обходит.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import strategies
from app.core.batfile import StrategySpec
from app.ui.controller import Controller, Status
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, KeyValueRow, view_header


class StrategiesView(QWidget):
    """Слева — список стратегий, справа — разбор выбранной."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._specs: list[StrategySpec] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Стратегии",
                "Набор правил обхода. Универсальной стратегии нет — у разных "
                "провайдеров работают разные, поэтому их и подбирают перебором.",
            )
        )

        columns = QHBoxLayout()
        columns.setSpacing(SPACE["lg"])
        columns.addWidget(self._build_list_card(), 2)
        columns.addWidget(self._build_detail_card(), 3)
        layout.addLayout(columns, 1)

        controller.status_changed.connect(self._apply_status)

    def _build_list_card(self) -> Card:
        card = Card("Доступные стратегии")
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._show_details)
        card.add(self._list)
        return card

    def _build_detail_card(self) -> Card:
        card = Card("Что делает стратегия")
        body = card.body()

        self._name = QLabel("—")
        self._name.setObjectName("ViewTitle")
        body.addWidget(self._name)

        self._row_sections = KeyValueRow("Секций обхода")
        self._row_args = KeyValueRow("Аргументов winws")
        body.addWidget(self._row_sections)
        body.addWidget(self._row_args)

        self._sections = QListWidget()
        self._sections.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        body.addWidget(self._sections, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE["sm"])
        self._apply_button = QPushButton("Применить и включить")
        self._apply_button.setObjectName("Primary")
        self._apply_button.clicked.connect(self._apply_selected)
        buttons.addWidget(self._apply_button)

        self._select_button = QPushButton("Только выбрать")
        self._select_button.clicked.connect(self._select_only)
        buttons.addWidget(self._select_button)

        self._favorite_button = QPushButton("В избранное")
        self._favorite_button.setToolTip(
            "Избранные поднимаются в начало списка и попадают в меню трея"
        )
        self._favorite_button.clicked.connect(self._toggle_favorite)
        buttons.addWidget(self._favorite_button)
        buttons.addStretch(1)
        body.addLayout(buttons)

        return card

    # --- данные ---------------------------------------------------------

    def reload(self) -> None:
        """Перечитывает стратегии с диска — например, после обновления ядра."""
        self._specs = strategies.load_all()
        selected = self.controller.settings.selected_strategy

        # Избранные наверх, остальные в прежнем порядке: так до нужной
        # стратегии не приходится пролистывать два десятка чужих.
        favorites = self.controller.settings.favorites
        self._specs.sort(key=lambda spec: spec.name not in favorites)

        self._list.clear()
        for spec in self._specs:
            item = QListWidgetItem(spec.name)
            item.setData(Qt.ItemDataRole.UserRole, spec.name)
            self._list.addItem(item)

        if not self._specs:
            self._name.setText("Ядро не установлено")
            self._sections.clear()
            self._apply_button.setEnabled(False)
            self._select_button.setEnabled(False)
            return

        self._apply_button.setEnabled(True)
        self._select_button.setEnabled(True)

        index = next((i for i, spec in enumerate(self._specs) if spec.name == selected), 0)
        self._list.setCurrentRow(index)

    def _show_details(self, row: int) -> None:
        if not (0 <= row < len(self._specs)):
            return

        spec = self._specs[row]
        self._name.setText(spec.name)
        self._row_sections.set_value(str(len(spec.sections)))
        self._row_args.set_value(str(len(spec.argv)))

        self._sync_favorite_button()

        self._sections.clear()
        for number, section in enumerate(spec.sections, start=1):
            self._sections.addItem(f"{number}.  {section.describe()}")

    def _current_spec(self) -> StrategySpec | None:
        row = self._list.currentRow()
        return self._specs[row] if 0 <= row < len(self._specs) else None

    def _sync_favorite_button(self) -> None:
        spec = self._current_spec()
        if spec is None:
            self._favorite_button.setEnabled(False)
            return
        self._favorite_button.setEnabled(True)
        in_favorites = spec.name in self.controller.settings.favorites
        self._favorite_button.setText("Убрать из избранного" if in_favorites else "В избранное")

    def _toggle_favorite(self) -> None:
        spec = self._current_spec()
        if spec is None:
            return

        settings = self.controller.settings
        if spec.name in settings.favorites:
            settings.favorites.remove(spec.name)
            self.controller.message.emit(f"«{spec.name}» убрана из избранного")
        else:
            settings.favorites.append(spec.name)
            self.controller.message.emit(f"«{spec.name}» добавлена в избранное")

        settings.save()
        self.reload()

    def _select_only(self) -> None:
        spec = self._current_spec()
        if spec is not None:
            self.controller.select_strategy(spec.name)
            self.controller.message.emit(f"Выбрана стратегия «{spec.name}»")

    def _apply_selected(self) -> None:
        spec = self._current_spec()
        if spec is None:
            return
        self.controller.select_strategy(spec.name)
        self.controller.stop()
        self.controller.start()

    def _apply_status(self, status: Status) -> None:
        """Помечает в списке стратегию, с которой обход работает прямо сейчас."""
        favorites = self.controller.settings.favorites
        for row in range(self._list.count()):
            item = self._list.item(row)
            name = item.data(Qt.ItemDataRole.UserRole)
            star = "★ " if name in favorites else ""

            if name == status.active_strategy and status.is_active:
                item.setText(f"{star}{name}   ● активна")
                item.setForeground(Qt.GlobalColor.white)
            elif name == self.controller.settings.selected_strategy:
                item.setText(f"{star}{name}   ○ выбрана")
            else:
                item.setText(f"{star}{name}")

        self._sync_favorite_button()

        self._apply_button.setText(
            "Применить и перезапустить" if status.is_active else "Применить и включить"
        )
        self._name.setStyleSheet(f"color: {COLORS['text']};")
