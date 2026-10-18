"""Экран поддержки проекта.

Программа бесплатная и открытая, и обход блокировок тем более не та вещь,
которую стоит прятать за оплату. Поэтому здесь не продажа, а благодарность:
ссылка на Boosty и список тех, кто поддержал.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import supporters
from app.core.supporters import SupportersList
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, Divider, banner_pixmap, view_header
from app.ui.workers import Task

log = logging.getLogger(__name__)

WHAT_IT_PAYS_FOR = (
    "На что идут деньги:\n"
    "• подпись сборки сертификатом — без неё Windows ругается на каждый запуск;\n"
    "• разбор неполадок нейросетью на общем ключе, чтобы не нужно было заводить свой;\n"
    "• время на поддержку, когда у провайдеров меняются правила."
)


REPO_URL = "https://github.com/igorxmel/ZapretXmel"
ISSUES_URL = f"{REPO_URL}/issues/new"

# Те, кто ловил поломки на себе, пока их не поймали все остальные.
TESTERS = ("Dencraz", "Drendr", "DynamitNS")


class SupportView(QWidget):
    """Благодарность и ссылка на Boosty."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._task: Task | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Поддержка",
                "Программа бесплатная и останется такой. Если она сэкономила вам "
                "вечер возни с батниками — можно сказать спасибо.",
            )
        )

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

        pays = QLabel(WHAT_IT_PAYS_FOR)
        pays.setObjectName("Dim")
        pays.setWordWrap(True)
        body.addWidget(pays)

        boosty = QPushButton("Открыть Boosty")
        boosty.setObjectName("Primary")
        if supporters.BOOSTY_URL:
            boosty.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(supporters.BOOSTY_URL))
            )
        else:
            # Кнопки, которая ничего не делает, быть не должно: пока ссылки
            # нет, её просто нет.
            boosty.hide()
        body.addWidget(boosty)



        body.addStretch(1)
        return card

    def _build_people_card(self) -> Card:
        card = Card("Спасибо этим людям")
        body = card.body()

        # Тестировщики — отдельной строкой и первыми: поломки, которые они
        # ловят, стоят дороже денег, а узнать о них больше неоткуда.
        testers = QLabel(
            "Спасибо любимым тестировщикам: "
            + ", ".join(f"{name} ♥" for name in TESTERS)
        )
        testers.setWordWrap(True)
        body.addWidget(testers)

        # Помогает не только деньгами: найденная поломка стоит дороже, а
        # звезда — единственный способ для случайного человека сказать, что
        # программа пригодилась.
        helping = QLabel(
            "Помочь можно и бесплатно: рассказать о поломке или поставить "
            "звезду на GitHub — по ней программу находят другие."
        )
        helping.setObjectName("Muted")
        helping.setWordWrap(True)
        body.addWidget(helping)

        issue = QPushButton("Сообщить о поломке")
        issue.setToolTip(
            "Откроется страница issue на GitHub. Приложите журнал из раздела "
            "«Логи» — по нему видно, что именно случилось."
        )
        issue.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ISSUES_URL)))
        body.addWidget(issue)

        star = QPushButton("Поставить звезду на GitHub")
        star.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        body.addWidget(star)

        body.addWidget(Divider())

        self._list = QListWidget()
        body.addWidget(self._list, 1)

        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])

        refresh = QPushButton("Обновить список")
        refresh.clicked.connect(self._refresh)
        row.addWidget(refresh)
        row.addStretch(1)
        body.addLayout(row)

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        body.addWidget(self._status)

        return card

    # --- данные ---------------------------------------------------------

    def reload(self) -> None:
        """Показывает сохранённый список сразу, а свежий подтягивает фоном."""
        self._show(supporters.cached())
        self._refresh()

    def _refresh(self) -> None:
        self._say("Обновляю список…")
        self._task = Task(supporters.fetch)
        self._task.done.connect(self._show)
        self._task.failed.connect(lambda message: self._say(message, COLORS["danger"]))
        self._task.start()

    def _show(self, people: SupportersList) -> None:
        self._list.clear()
        for person in people.people:
            self._list.addItem(person.label)

        if people.is_empty:
            self._say(
                "Пока никого — и это нормально: список появится, когда появятся "
                "поддержавшие."
            )
            return

        source = "из сохранённого" if people.from_cache else f"обновлён {people.updated}"
        self._say(f"Поддержавших: {len(people.people)} ({source})")

    def _say(self, text: str, colour: str = COLORS["text_muted"]) -> None:
        self._status.setStyleSheet(f"color: {colour};")
        self._status.setText(text)
