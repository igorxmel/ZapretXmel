"""Экран поддержки: кому спасибо, куда сообщить о поломке и адреса кошельков."""

from __future__ import annotations

import time
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
from app.core.updater import github
from app.ui.controller import Controller
from app.ui.theme.tokens import BRAND, COLORS, SPACE
from app.ui.widgets import Card, Divider, banner_pixmap, view_header
from app.ui.workers import Task

WALLETS_NOTE = (
    "Программа бесплатная и останется такой, поддержка добровольная. Переводите только в указанной "
    "сети: перевод в другой сети может пропасть, а отменить его нельзя."
)

REPO = "igorxmel/ZapretXmel"
REPO_URL = f"https://github.com/{REPO}"
# Лимит GitHub общий на адрес, поэтому спрашиваем не при каждом открытии экрана.
STARS_REFRESH_SECONDS = 600
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
        self._stars_task: Task | None = None
        self._stars_asked_at: float | None = None
        self._star_count: int | None = None

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

        body.addWidget(Divider())

        self._stars = QLabel()
        self._stars.setObjectName("ViewTitle")
        self._stars.setTextFormat(Qt.TextFormat.RichText)
        self._paint_stars()
        body.addWidget(self._stars)

        asking = QLabel(
            "Если программа пригодилась, поставьте ей звезду и поделитесь ею с друзьями: "
            "так о ней узнают те, кому она тоже может помочь."
        )
        asking.setObjectName("Dim")
        asking.setWordWrap(True)
        body.addWidget(asking)

        star = QPushButton("Поставить звезду на GitHub")
        star.setObjectName("Primary")
        star.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        body.addWidget(star)

        self.share_button = QPushButton("Скопировать ссылку для друзей")
        self.share_button.clicked.connect(self._copy_link)
        body.addWidget(self.share_button)

        body.addStretch(1)
        return card

    def _copy_link(self) -> None:
        QApplication.clipboard().setText(REPO_URL)
        self.share_button.setText("Ссылка скопирована")

    def _ask_for_stars(self) -> None:
        running = self._stars_task is not None and self._stars_task.isRunning()
        asked = self._stars_asked_at
        if running or (asked is not None and time.monotonic() - asked < STARS_REFRESH_SECONDS):
            return

        self._stars_asked_at = time.monotonic()
        self._stars_task = Task(github.repo_stars, REPO)
        self._stars_task.done.connect(self._show_stars)
        self._stars_task.start()

    def _show_stars(self, stars: int | None) -> None:
        """Не узнали — оставляем то, что уже показано: прошлое число лучше ошибки."""
        if stars is not None:
            self._star_count = stars
            self._paint_stars()

    def _paint_stars(self) -> None:
        """Как и сердечки ниже: цвет в разметке, поэтому при смене темы строка собирается заново."""
        count = "—" if self._star_count is None else self._star_count
        star = f'<span style="color: {BRAND["orange"]};">&#9733;</span>'
        self._stars.setText(f"{star} Звёзд на GitHub: {count}")

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
        self._paint_stars()
        self.share_button.setText("Скопировать ссылку для друзей")
        self._ask_for_stars()
