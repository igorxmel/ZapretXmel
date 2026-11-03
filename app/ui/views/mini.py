"""Мини-окно: две кнопки, выбор стратегии и проверка.

Большинству людей каждый день нужно только это. Всё остальное спрятано в меню снизу
и открывается в полном окне: таблицы и настройки в такую ширину не помещаются.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.controller import Controller, Status
from app.ui.frameless import SVG_ICON_SIZE, svg_icon
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.views.controls import PowerPair, QuickPanel, StatusNotices
from app.ui.widgets import banner_pixmap

BANNER_WIDTH = 230


class MiniView(QWidget):
    """Содержимое окна в мини-режиме."""

    section_requested = pyqtSignal(str)
    install_core_requested = pyqtSignal()
    install_proxy_requested = pyqtSignal()

    def __init__(
        self,
        controller: Controller,
        sections: tuple[tuple[str, str], ...],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Прокрутка нужна на маленьких экранах и при длинном ответе проверки:
        # окно не растягивается, и текст иначе обрезался бы.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        layout.setSpacing(SPACE["md"])
        scroll.setWidget(content)

        banner = QLabel()
        banner.setPixmap(banner_pixmap(BANNER_WIDTH))
        banner.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(banner)

        self.power = PowerPair(controller, spacing=SPACE["md"])
        self.power.install_core_requested.connect(self.install_core_requested)
        self.power.install_proxy_requested.connect(self.install_proxy_requested)
        layout.addWidget(self.power)

        self.notices = StatusNotices()
        layout.addWidget(self.notices)

        self.panel = QuickPanel(controller)
        layout.addWidget(self.panel)
        # Прокручиваем после раскладки: до неё у новой строки нет настоящего места.
        self.panel.answer_shown.connect(
            lambda: QTimer.singleShot(0, lambda: scroll.ensureWidgetVisible(self.panel.answer))
        )

        layout.addStretch(1)

        footer = QVBoxLayout()
        footer.setContentsMargins(SPACE["lg"], SPACE["sm"], SPACE["lg"], SPACE["md"])
        footer.setSpacing(SPACE["sm"])
        outer.addLayout(footer)

        # Полосы обновления здесь нет, а узнать о них человек всё равно должен.
        self._update = QPushButton("Есть обновления")
        self._update.setObjectName("Chip")
        self._update.setProperty("alert", True)
        self._update.clicked.connect(lambda: self.section_requested.emit("updates"))
        self._update.hide()
        footer.addWidget(self._update, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.toast = QLabel("")
        self.toast.setObjectName("Muted")
        self.toast.setWordWrap(True)
        footer.addWidget(self.toast)

        self.menu_button = QPushButton("Все разделы")
        self.menu_button.setToolTip("Подбор, списки, настройки и остальное. Откроется полное окно")
        self._menu = QMenu(self)
        for key, title in sections:
            if key != "dashboard":
                action = QAction(title, self)
                action.triggered.connect(lambda _, target=key: self.section_requested.emit(target))
                self._menu.addAction(action)
        self.menu_button.setMenu(self._menu)
        footer.addWidget(self.menu_button)

        controller.status_changed.connect(self.apply_status)

    def reload(self) -> None:
        self.panel.reload()
        # Заново при каждом входе в мини-окно: тему могли сменить в настройках.
        self.menu_button.setIcon(svg_icon("window-sections", COLORS["text"]))
        self.menu_button.setIconSize(QSize(SVG_ICON_SIZE, SVG_ICON_SIZE))

    def apply_status(self, status: Status) -> None:
        self.power.apply_status(status)
        self.notices.apply_status(status)
        self.panel.apply_status(status)

    def set_update_available(self, available: bool) -> None:
        self._update.setVisible(available)
