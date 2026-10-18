"""Окно «что нового» — показывается один раз после обновления.

Человек нажал «Обновить и перезапустить», программа закрылась и открылась
снова — и внешне ничего не изменилось. Что именно починили и ради чего была
эта пауза, он узнавал только на GitHub, то есть не узнавал никогда.

Текст берётся из `CHANGELOG.md`, который едет внутри сборки: сети может не
быть именно из-за тех блокировок, ради которых программу и поставили.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from app import __version__
from app.core import changelog
from app.ui.frameless import FramelessWindow
from app.ui.theme.tokens import SPACE
from app.ui.widgets import Card, banner_pixmap, set_markdown

log = logging.getLogger(__name__)

RELEASES = "https://github.com/igorxmel/ZapretXmel/releases"


class WhatsNewWindow(FramelessWindow):
    """Короткий рассказ о том, что изменилось в этой версии."""

    closed = pyqtSignal()

    def __init__(self, notes: str, parent: QWidget | None = None):
        super().__init__("Что нового", compact=True)

        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFixedWidth(640)
        self.setMinimumHeight(520)

        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(SPACE["xxl"], SPACE["xl"], SPACE["xxl"], SPACE["xl"])
        layout.setSpacing(SPACE["md"])

        banner = QLabel()
        banner.setPixmap(banner_pixmap(320))
        banner.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(banner)

        title = QLabel(f"Обновились до {__version__}")
        title.setObjectName("ViewTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        card = Card()
        notes_view = QTextBrowser()
        notes_view.setOpenExternalLinks(True)
        set_markdown(notes_view, notes)
        card.add(notes_view)
        layout.addWidget(card, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE["sm"])

        all_versions = QPushButton("Все версии")
        all_versions.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES)))
        buttons.addWidget(all_versions)

        buttons.addStretch(1)

        close = QPushButton("Понятно")
        close.setObjectName("Primary")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def closeEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        self.closed.emit()
        event.accept()


def notes_for_current_version() -> str:
    """Текст для окна. Пусто — значит показывать нечего."""
    return changelog.read(__version__)


def should_show(seen: str, current: str, first_run_done: bool) -> bool:
    """Показывать ли окно «что нового».

    Пустая отметка о просмотре значит две разные вещи: либо программу
    запустили впервые, либо обновились с версии, которая эту отметку ещё не
    вела. Различает их `first_run_done`: человек, прошедший знакомство,
    новичком уже не является — ему окно показать надо.
    """
    if seen == current:
        return False
    return bool(seen) or first_run_done
