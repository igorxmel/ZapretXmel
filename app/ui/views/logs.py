"""Экран логов: вывод winws и журнал самого приложения."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import paths
from app.ui.controller import Controller
from app.ui.theme.tokens import SPACE
from app.ui.widgets import Card, view_header

MAX_LINES = 2000


class LogsView(QWidget):
    """Живой вывод winws — первое место, куда стоит смотреть, если обход падает."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Логи",
                "Вывод winws виден только в режиме обычного процесса: запущенная "
                "как служба программа пишет в системный журнал, а не нам.",
            )
        )

        card = Card()
        body = card.body()

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(MAX_LINES)
        body.addWidget(self._view, 1)

        footer = QHBoxLayout()
        footer.setSpacing(SPACE["md"])

        clear_button = QPushButton("Очистить")
        clear_button.clicked.connect(self._view.clear)
        footer.addWidget(clear_button)

        folder_button = QPushButton("Открыть папку с логами")
        folder_button.clicked.connect(self._open_folder)
        footer.addWidget(folder_button)
        footer.addStretch(1)
        body.addLayout(footer)

        layout.addWidget(card, 1)

        controller.log_line.connect(self.append)

    def append(self, line: str) -> None:
        self._view.appendPlainText(line)

    def load_tail(self, lines: list[str]) -> None:
        """Подхватывает уже накопленный вывод при первом открытии экрана."""
        if lines and not self._view.toPlainText():
            self._view.setPlainText("\n".join(lines))

    def _open_folder(self) -> None:
        paths.ensure_dirs()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.logs_dir())))
