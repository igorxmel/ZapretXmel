"""Экран выбора стратегии.

Список строится сканированием папки ядра, поэтому стратегии из нового релиза
Flowseal появляются здесь сами. Для каждой показывается разбор по секциям —
видно, какие порты и списки она затрагивает и каким способом обходит.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core import stability, strategies, strategycheck
from app.core.batfile import StrategySpec
from app.ui.controller import Controller, Status
from app.ui.strategy_parts import (
    BROKEN_ROLE,
    FAVORITE_ROLE,
    NAME_ROLE,
    PERCENT_ROLE,
    STATE_ROLE,
    SectionRow,
    StrategyDelegate,
    rate_colour,
)
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, KeyValueRow, view_header
from app.ui.workers import Task

log = logging.getLogger(__name__)


class StrategiesView(QWidget):
    """Слева — список стратегий, справа — разбор выбранной."""

    # Проверка запуска закончилась — обзору пора перечитать свой список стратегий.
    checked = pyqtSignal()

    # Через сколько после старта проверить стратегии, не дожидаясь, пока откроют раздел:
    # пометка «не запускается» нужна и в списке на обзоре. Не сразу — запуск и так занят.
    CHECK_AFTER_START_MS = 8000

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._specs: list[StrategySpec] = []
        # Стратегии, которые winws не может даже разобрать: имя → причина.
        self._broken: dict[str, str] = strategycheck.known_broken()
        self._check_task: Task | None = None

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
        QTimer.singleShot(self.CHECK_AFTER_START_MS, self._check_after_start)

    def _build_list_card(self) -> Card:
        card = Card("Доступные стратегии")
        self._list = QListWidget()
        self._list.setObjectName("StrategyList")
        self._list.setItemDelegate(StrategyDelegate(self._list))
        self._list.setMouseTracking(True)
        # Длинное имя обрезается многоточием, а не уводит строку вбок.
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.currentRowChanged.connect(self._show_details)
        self._list.itemDoubleClicked.connect(lambda _item: self._apply_selected())
        card.add(self._list)

        # Свои стратегии складываются в ту же папку и переживают обновление
        # ядра: апдейтер переносит всё, чего нет в новой сборке.
        own = QHBoxLayout()
        own.setSpacing(SPACE["sm"])

        self._add_button = QPushButton("Добавить свою…")
        self._add_button.setToolTip("Взять готовый .bat и положить его в папку ядра")
        self._add_button.clicked.connect(self._add_own)
        own.addWidget(self._add_button)

        self._copy_button = QPushButton("Копия для правки")
        self._copy_button.setToolTip(
            "Сделать копию выбранной стратегии под своим именем и открыть её — "
            "писать с нуля почти никто не станет, а поправить готовую несложно"
        )
        self._copy_button.clicked.connect(self._duplicate_selected)
        own.addWidget(self._copy_button)

        card.body().addLayout(own)
        return card

    # --- свои стратегии ---------------------------------------------------

    def _add_own(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл стратегии",
            str(Path.home()),
            "Стратегии zapret (*.bat)",
        )
        if not chosen:
            return

        try:
            added = strategies.add(Path(chosen))
        except Exception as error:  # noqa: BLE001 — причину показываем пользователю
            log.exception("Не удалось добавить стратегию")
            self.controller.error.emit(str(error))
            return

        self.controller.message.emit(f"Добавлена стратегия «{added.stem}»")
        self.reload()
        self._select_by_name(added.stem)

    def _duplicate_selected(self) -> None:
        spec = self._current_spec()
        if spec is None:
            return

        try:
            copy = strategies.duplicate(spec.name)
        except Exception as error:  # noqa: BLE001 — причину показываем пользователю
            log.exception("Не удалось скопировать стратегию")
            self.controller.error.emit(str(error))
            return

        self.reload()
        self._select_by_name(copy.stem)
        self.controller.message.emit(
            f"Создана «{copy.stem}» — откройте её и правьте, исходная осталась как была"
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(copy)))

    def _select_by_name(self, name: str) -> None:
        for row in range(self._list.count()):
            if self._list.item(row).text().startswith(name):
                self._list.setCurrentRow(row)
                return

    def _build_detail_card(self) -> Card:
        card = Card("Что делает стратегия")
        body = card.body()

        self._name = QLabel("—")
        self._name.setObjectName("ViewTitle")
        body.addWidget(self._name)

        # Сводка строками «подпись — значение». Плитки с крупными цифрами пробовали в
        # 0.5.0: «05–08» без подписи рядом не читалось, а цвет спорил с секциями ниже.
        self._row_launch = KeyValueRow("Запуск")
        self._row_launch.setToolTip(
            "winws проверяет стратегию, не перехватывая трафик: разбирает аргументы и сразу"
            " выходит. Не запускается — значит, ни подбор, ни ручное включение с ней не"
            " заработают. Справа — причина словами самого winws."
        )
        self._row_launch.hide()
        self._row_stability = KeyValueRow("Стабильность")
        self._row_stability.setToolTip(
            "Проверки сторожа за последние две недели, пока эта стратегия работала. Одиночный"
            " сбой не считается, если следующая проверка прошла. Если файл стратегии изменился,"
            " счёт начинается заново. Хранится только на этом компьютере."
        )
        self._row_services = KeyValueRow("По сервисам")
        self._row_services.setToolTip(
            "Как часто каждый сервис работал с этой стратегией за последние две недели. Помогает"
            " понять, что именно у неё отваливается."
        )
        self._row_hours = KeyValueRow("Сбои")
        self._row_hours.setToolTip(
            "Когда сбои собираются в одни и те же часы, дело обычно в провайдере: многие строже"
            " вечером. Стратегия при этом может быть лучшей из доступных."
        )
        self._row_sections = KeyValueRow("Секций обхода")
        rows = (
            self._row_launch, self._row_stability, self._row_services, self._row_hours,
            self._row_sections,
        )
        for row in rows:
            body.addWidget(row)
        KeyValueRow.line_up(*rows)

        # Отметки «98%» в списке. Считаются при перечитывании, а не на каждом опросе состояния:
        # опрос идёт раз в несколько секунд и читал бы журнал по кругу.
        self._marks: dict[str, str] = {}

        # Секции — строками с таблетками, а не сырой строкой аргументов.
        self._sections_box = QWidget()
        self._sections_layout = QVBoxLayout(self._sections_box)
        self._sections_layout.setContentsMargins(0, 0, SPACE["sm"], 0)
        self._sections_layout.setSpacing(SPACE["xs"])
        self._sections_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("SectionsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._sections_box)
        body.addWidget(scroll, 1)

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

        self._marks = stability.marks([spec.name for spec in self._specs])
        self._list.clear()
        for spec in self._specs:
            item = QListWidgetItem(spec.name)
            item.setData(NAME_ROLE, spec.name)
            self._list.addItem(item)

        if not self._specs:
            self._name.setText("Ядро не установлено")
            self._fill_sections([])
            self._apply_button.setEnabled(False)
            self._select_button.setEnabled(False)
            return

        self._apply_button.setEnabled(True)
        self._select_button.setEnabled(True)

        index = next((i for i, spec in enumerate(self._specs) if spec.name == selected), 0)
        self._list.setCurrentRow(index)
        self._check_strategies()

    def _check_strategies(self) -> None:
        """В фоне: запускается ли каждая стратегия. Проверяется только изменившееся."""
        if self._check_task is not None and self._check_task.isRunning():
            return
        self._check_task = Task(strategycheck.check_all, list(self._specs))
        self._check_task.done.connect(self._strategies_checked)
        self._check_task.failed.connect(
            lambda message: log.warning("Проверка стратегий не удалась: %s", message)
        )
        self._check_task.start()

    def _check_after_start(self) -> None:
        if not self._specs:
            self._specs = strategies.load_all()
        if self._specs:
            self._check_strategies()

    def _strategies_checked(self, broken: dict[str, str]) -> None:
        changed = broken != self._broken
        self._broken = broken
        self._apply_status(self.controller.status)
        self._show_details(self._list.currentRow())
        if changed:
            self.checked.emit()

    def _show_details(self, row: int) -> None:
        if not (0 <= row < len(self._specs)):
            return

        spec = self._specs[row]
        self._name.setText(spec.name)
        reason = self._broken.get(spec.name, "")
        self._row_launch.setVisible(bool(reason))
        if reason:
            self._row_launch.set_value(f"не запускается — {reason}")
            self._row_launch.set_value_color(COLORS["danger"])

        mark = self._marks.get(spec.name, "")
        described = stability.describe(spec.name)
        if mark:
            colour = rate_colour(int(mark.rstrip("%")))
            self._row_stability.set_value(
                f'<span style="color:{colour}; font-weight:600">{mark}</span>'
                f"&nbsp;&nbsp;{described.removeprefix('прошла ')}"
            )
        else:
            self._row_stability.set_value(described)

        rates = stability.service_rates(spec.name)
        self._row_services.set_value(
            "&nbsp;&nbsp;·&nbsp;&nbsp;".join(
                f'{service} <span style="color:{rate_colour(percent)}; font-weight:600">'
                f"{percent}%</span>"
                for service, percent in rates
            )
            if rates else "пока мало проверок"
        )
        hours = stability.describe_hours(spec.name)
        self._row_hours.set_value(hours)
        self._row_hours.setVisible(bool(hours))
        self._row_sections.set_value(
            f"{len(spec.sections)}&nbsp;&nbsp;"
            f'<span style="color:{COLORS["text_muted"]}">'
            f"аргументов winws: {len(spec.argv)}</span>"
        )

        self._sync_favorite_button()
        self._fill_sections(spec.sections)

    def _fill_sections(self, sections: list) -> None:
        layout = self._sections_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().deleteLater()
        for number, section in enumerate(sections, start=1):
            layout.insertWidget(layout.count() - 1, SectionRow(number, section))

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
        """Помечает в списке стратегию, с которой обход работает прямо сейчас.

        Всё рисует `StrategyDelegate` по данным строки: точка состояния, звезда избранного,
        процент стабильности и «не запускается». Текст строки — только имя: по нему её ищут.
        """
        favorites = self.controller.settings.favorites
        selected = self.controller.settings.selected_strategy
        for row in range(self._list.count()):
            item = self._list.item(row)
            name = item.data(NAME_ROLE)
            if name == status.active_strategy and status.is_active:
                state = "active"
            elif name == selected:
                state = "selected"
            else:
                state = ""
            mark = self._marks.get(name)
            item.setData(STATE_ROLE, state)
            item.setData(FAVORITE_ROLE, name in favorites)
            item.setData(BROKEN_ROLE, name in self._broken)
            item.setData(PERCENT_ROLE, int(mark.rstrip("%")) if mark else None)
            hint = {"active": "работает сейчас", "selected": "выбрана, но обход выключен"}
            item.setToolTip(f"{name}\n{hint[state]}" if state else name)

        self._sync_favorite_button()

        self._apply_button.setText(
            "Применить и перезапустить" if status.is_active else "Применить и включить"
        )
        self._name.setStyleSheet(f"color: {COLORS['text']};")
