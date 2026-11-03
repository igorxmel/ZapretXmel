"""Экран поддержки: кому спасибо, куда сообщить о поломке и адреса кошельков."""

from __future__ import annotations

from html import escape

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import donate
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, banner_pixmap, view_header

WALLETS_NOTE = (
    "Программа бесплатная и останется такой, поддержка добровольная. Переводите только в указанной "
    "сети: перевод в другой сети может пропасть, а отменить его нельзя."
)

REPO_URL = "https://github.com/igorxmel/ZapretXmel"
ISSUES_URL = f"{REPO_URL}/issues/new"

# Те, кто ловил поломки на себе, пока их не поймали все остальные.
TESTERS = ("Dencraz", "Drendr", "DynamitNS")


class WalletRow(QWidget):
    """Адрес кошелька с кнопкой копирования: перепечатывать его руками опасно."""

    def __init__(self, wallet: donate.Wallet, parent: QWidget | None = None):
        super().__init__(parent)
        self.wallet = wallet

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["xs"])
        layout.addWidget(QLabel(wallet.title))

        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])

        address = QLabel(wallet.address)
        address.setObjectName("Dim")
        address.setWordWrap(True)
        address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(address, 1)

        self.copy_button = QPushButton("Скопировать")
        self.copy_button.clicked.connect(self._copy)
        row.addWidget(self.copy_button)
        layout.addLayout(row)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.wallet.address)
        self.copy_button.setText("Скопировано")


class SupportView(QWidget):
    """Благодарность и способы помочь проекту."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(view_header("Поддержка", "Кому спасибо и как помочь проекту."))

        columns = QHBoxLayout()
        columns.setSpacing(SPACE["lg"])
        columns.addWidget(self._build_about_card(), 1)
        columns.addWidget(self._build_people_card(), 1)
        layout.addLayout(columns, 1)

    def _build_about_card(self) -> Card:
        card = Card()
        body = card.body()

        banner = QLabel()
        banner.setPixmap(banner_pixmap(320))
        banner.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        body.addWidget(banner)

        self.wallet_rows = [WalletRow(wallet) for wallet in donate.WALLETS]
        if self.wallet_rows:
            note = QLabel(WALLETS_NOTE)
            note.setObjectName("Muted")
            note.setWordWrap(True)
            body.addWidget(note)
            for row in self.wallet_rows:
                body.addWidget(row)

        body.addStretch(1)
        return card

    def _build_people_card(self) -> Card:
        card = Card("Спасибо этим людям")
        body = card.body()

        # Поломки, которые тестировщики ловят, стоят дороже денег, а узнать о них больше неоткуда.
        self._testers = QLabel()
        self._testers.setTextFormat(Qt.TextFormat.RichText)
        self._testers.setWordWrap(True)
        self._paint_testers()
        body.addWidget(self._testers)

        issue = QPushButton("Сообщить о поломке")
        issue.setToolTip(
            "Откроется страница issue на GitHub. Приложите журнал из раздела "
            "«Логи» — по нему видно, что именно случилось."
        )
        issue.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ISSUES_URL)))
        body.addWidget(issue)

        body.addStretch(1)
        return card

    def _paint_testers(self) -> None:
        """Собирает строку заново — из-за одного красного сердечка.

        Цвет запечён в разметке, а таблица стилей до неё не достаёт, поэтому после смены
        оформления строку приходится пересобирать. Делается это при открытии экрана, потому
        что тему меняют в настройках, на другом экране.

        Имена экранируются: разметка тут ради сердечка, а не ради имён.
        """
        heart = f'<span style="color: {COLORS["heart"]};">&#9829;</span>'
        self._testers.setText(
            "Спасибо любимым тестировщикам: "
            + ", ".join(f"{escape(name)} {heart}" for name in TESTERS)
        )

    def reload(self) -> None:
        self._paint_testers()
