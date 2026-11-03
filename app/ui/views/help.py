"""Окно «Как пользоваться»: короткие шаги и частые вопросы."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QTextBrowser, QVBoxLayout

from app.core import guide
from app.ui.frameless import FramelessWindow
from app.ui.theme.tokens import SPACE
from app.ui.widgets import Card, set_markdown


class HelpWindow(FramelessWindow):
    """Справка. Вопросы берутся из FAQ.md, поэтому второй текст поддерживать не нужно."""

    def __init__(self):
        super().__init__("Как пользоваться", compact=True, resizable=True, caption="Справка")
        # На ноутбуке с увеличением экрана в логических точках совсем немного.
        screen = QApplication.primaryScreen()
        room = screen.availableGeometry().height() if screen else 720
        self.setMinimumSize(560, min(480, int(room * 0.9)))
        self.resize(680, min(720, int(room * 0.94)))

        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        layout.setSpacing(SPACE["md"])

        title = QLabel("Как пользоваться")
        title.setObjectName("ViewTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        card = Card()
        self.text = QTextBrowser()
        self.text.setObjectName("HelpText")
        self.text.setOpenExternalLinks(True)
        set_markdown(self.text, guide.help_markdown())
        card.add(self.text)
        layout.addWidget(card, 1)

        close = QPushButton("Понятно")
        close.setObjectName("Primary")
        close.clicked.connect(self.close)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
