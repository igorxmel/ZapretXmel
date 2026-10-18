"""Панель разбора нейросетью.

Живёт на экране диагностики рядом с проверками по правилам. Правила ловят
известное и работают всегда; сюда обращаются за тем, чего в правилах нет.

Выгрузка пакета намеренно не требует ключа: это основной путь для тех, кто не
хочет ничего подключать, — забрал архив и отдал любому чат-боту.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.diagnostics import bundle
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.views.aiwindow import AiWindow
from app.ui.widgets import Card, Divider
from app.ui.workers import Task

log = logging.getLogger(__name__)


class AiPanel(QWidget):
    """Описание проблемы, выбор сервиса и разбор."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._task: Task | None = None
        self._window: AiWindow | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(self._build_card(), 1)

    def _build_card(self) -> Card:
        card = Card("Разбор нейросетью")
        body = card.body()

        hint = QLabel(
            "Проверки слева ловят известные причины. Нейросеть нужна для случаев, "
            "которых в них нет: странный лог, непонятное сочетание настроек."
        )
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        body.addWidget(hint)

        body.addWidget(QLabel("Что не работает"))
        self._problem = QPlainTextEdit()
        self._problem.setPlaceholderText(
            "Например: Discord не подключается, висит на Connecting. YouTube работает."
        )
        self._problem.setMaximumHeight(70)
        body.addWidget(self._problem)

        body.addWidget(Divider())

        export_row = QHBoxLayout()
        export_row.setSpacing(SPACE["sm"])

        export = QPushButton("Выгрузить пакет для любого ИИ")
        export.setObjectName("Primary")
        export.setToolTip(
            "Архив с данными, пояснением к ним и готовым запросом — "
            "ключ не нужен, отдать можно любому чат-боту"
        )
        export.clicked.connect(self._export)
        export_row.addWidget(export)
        export_row.addStretch(1)
        body.addLayout(export_row)

        body.addWidget(Divider())

        # Разбор переехал в своё окно: здесь ему было тесно — названия
        # моделей не помещались в узкий список, а ответ на несколько
        # абзацев читался в окошке высотой в пять строк.
        ask = QPushButton("Разобрать нейросетью…")
        ask.setToolTip(
            "Откроется отдельное окно: там видно названия моделей целиком, "
            "хватает места ответу и сохраняются прошлые разборы"
        )
        ask.clicked.connect(self._open_window)
        body.addWidget(ask)

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        body.addWidget(self._status)

        body.addStretch(1)

        return card

    # --- состояние -------------------------------------------------------

    def reload(self) -> None:
        """Обновлять здесь больше нечего: выбор сервиса живёт в своём окне."""

    def _export(self) -> None:
        self._say("Собираю пакет…")
        problem = self._problem.toPlainText()

        self._task = Task(bundle.export, problem=problem)
        self._task.done.connect(self._exported)
        self._task.failed.connect(self._fail)
        self._task.start()

    def _exported(self, path) -> None:
        self._say(f"Готово: {path.name}", COLORS["success"])
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        self.controller.message.emit(
            "Пакет собран. Внутри — данные, пояснение и готовый запрос: "
            "отдайте архив любому чат-боту целиком."
        )

    def _say(self, text: str, colour: str = COLORS["text_muted"]) -> None:
        self._status.setStyleSheet(f"color: {colour};")
        self._status.setText(text)

    def _open_window(self) -> None:
        """Открывает окно разбора. Одно на всё приложение, а не по окну на нажатие."""
        if self._window is None:
            self._window = AiWindow(self)

        # Описание уже набрано здесь — заставлять набирать его второй раз
        # в окне было бы издевательством.
        typed = self._problem.toPlainText().strip()
        if typed:
            self._window.set_problem(typed)

        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _fail(self, message: str) -> None:
        self._say(message, COLORS["danger"])
