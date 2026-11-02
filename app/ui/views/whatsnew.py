"""Окно «что нового» — показывается один раз после обновления.

Человек нажал «Обновить и перезапустить», программа закрылась и открылась
снова — и внешне ничего не изменилось. Что именно починили и ради чего была
эта пауза, он узнавал только на GitHub, то есть не узнавал никогда.

Текст берётся из `CHANGELOG.md`, который едет внутри сборки: сети может не
быть именно из-за тех блокировок, ради которых программу и поставили.

Обновляются не на каждую версию, поэтому в окне всё, что вышло с прошлого
обновления: последняя версия раскрыта, остальные свёрнуты.
"""

from __future__ import annotations

import logging
import math

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.core import changelog
from app.ui.frameless import FramelessWindow
from app.ui.theme.tokens import SPACE
from app.ui.widgets import Card, banner_pixmap, set_markdown

log = logging.getLogger(__name__)

RELEASES = "https://github.com/igorxmel/ZapretXmel/releases"
TALL_HEIGHT = 760


class _FittedNotes(QTextBrowser):
    """Описание версии во всю свою высоту: прокручивается общий список."""

    def __init__(self, notes: str):
        super().__init__()
        self.setObjectName("VersionNotes")
        self.setOpenExternalLinks(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        set_markdown(self, notes)

    def resizeEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        super().resizeEvent(event)
        self.document().setTextWidth(self.viewport().width())
        self.setFixedHeight(math.ceil(self.document().size().height()) + 2 * self.frameWidth())
        # Qt считает диапазон по прежней, маленькой высоте и не пересчитывает:
        # текст, который виден целиком, сдвигался клавишами и выделением.
        self.verticalScrollBar().setRange(0, 0)

    def wheelEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        # Своей прокрутки здесь нет, и колесо над текстом не делало ничего:
        # список крутился, только если навести курсор на заголовок версии.
        area = self.parentWidget()
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parentWidget()
        if area is not None:
            QApplication.sendEvent(area.verticalScrollBar(), event)


class _VersionSection(QWidget):
    """Версия с выпадающим описанием."""

    def __init__(self, entry: changelog.Entry, expanded: bool):
        super().__init__()
        self._entry = entry
        self._notes: _FittedNotes | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACE["xs"])

        self.toggle = QPushButton()
        self.toggle.setObjectName("VersionToggle")
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._show_notes)
        self._layout.addWidget(self.toggle)

        self._show_notes(False)
        self.toggle.setChecked(expanded)

    def _show_notes(self, shown: bool) -> None:
        # Плюс и минус есть в любом шрифте, стрелки — не в каждом.
        self.toggle.setText(f"{'−' if shown else '+'}  Версия {self._entry.version}")

        # Разделов десятки, а открывают один-два: разбирать разметку заранее незачем.
        if shown and self._notes is None:
            self._notes = _FittedNotes(self._entry.notes)
            self._layout.addWidget(self._notes)
        if self._notes is not None:
            self._notes.setVisible(shown)


def skipped_text(seen: str, entries: list[changelog.Entry]) -> str:
    """Подпись о пропущенных версиях. Одна версия в пояснении не нуждается."""
    if not seen or len(entries) < 2:
        return ""
    return f"С версии {seen} вышло обновлений: {len(entries)}"


class WhatsNewWindow(FramelessWindow):
    """Короткий рассказ о том, что изменилось."""

    closed = pyqtSignal()

    def __init__(
        self,
        entries: list[changelog.Entry],
        heading: str,
        subtitle: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__("Что нового", compact=True)

        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFixedWidth(640)
        self.setMinimumHeight(520)
        # Со списком версий нужно больше места, иначе из-за длинной первой
        # записи остальных не видно. Но ноутбучный экран бывает и в 768 точек.
        if len(entries) > 1:
            screen = QApplication.primaryScreen()
            room = screen.availableGeometry().height() - 60 if screen else TALL_HEIGHT
            self.resize(640, max(520, min(TALL_HEIGHT, room)))

        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(SPACE["xxl"], SPACE["xl"], SPACE["xxl"], SPACE["xl"])
        layout.setSpacing(SPACE["md"])

        banner = QLabel()
        banner.setPixmap(banner_pixmap(320))
        banner.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(banner)

        title = QLabel(heading)
        title.setObjectName("ViewTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        if subtitle:
            hint = QLabel(subtitle)
            hint.setObjectName("Muted")
            hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(hint)

        card = Card()
        card.add(self._build_notes(entries))
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

    def _build_notes(self, entries: list[changelog.Entry]) -> QWidget:
        if len(entries) == 1:
            notes_view = QTextBrowser()
            notes_view.setOpenExternalLinks(True)
            set_markdown(notes_view, entries[0].notes)
            return notes_view

        column = QWidget()
        rows = QVBoxLayout(column)
        rows.setContentsMargins(0, 0, SPACE["sm"], 0)
        rows.setSpacing(SPACE["xs"])

        self.sections = [
            _VersionSection(entry, expanded=index == 0) for index, entry in enumerate(entries)
        ]
        for section in self.sections:
            rows.addWidget(section)
        rows.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(column)
        self.scroll = scroll
        return scroll

    def closeEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        self.closed.emit()
        event.accept()


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
