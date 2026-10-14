"""Значок в системном трее.

Иконка рисуется в коде, а не берётся из файла: так приложение остаётся одним
исполняемым файлом без внешних ресурсов, а цвет значка сразу показывает,
включён обход или нет.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from app.ui.controller import Controller, Status
from app.ui.theme.tokens import COLORS
from app.ui.widgets import logo_pixmap


def app_icon() -> QIcon:
    """Значок приложения — логотип, если он на месте."""
    pixmap = logo_pixmap(256)
    return QIcon(pixmap) if not pixmap.isNull() else QIcon()


def build_icon(active: bool) -> QIcon:
    """Значок для трея: логотип с точкой состояния в углу.

    Выключенный обход показывается приглушённым логотипом — так значок
    остаётся узнаваемым, но не притворяется работающим.
    """
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    logo = logo_pixmap(size)
    if logo.isNull():
        painter.setPen(QPen(QColor(COLORS["text_dim"]), 6))
        painter.drawEllipse(QRectF(10, 10, size - 20, size - 20))
    else:
        if not active:
            painter.setOpacity(0.45)
        painter.drawPixmap(0, 0, logo)
        painter.setOpacity(1.0)

    dot = 18.0
    painter.setPen(QPen(QColor(COLORS["bg"]), 3))
    painter.setBrush(QColor(COLORS["success"] if active else COLORS["text_muted"]))
    painter.drawEllipse(QRectF(size - dot - 2, size - dot - 2, dot, dot))
    painter.end()

    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    """Управление обходом, не открывая окно."""

    show_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller

        self.setIcon(build_icon(False))
        self.setToolTip("ZapretXmel")

        menu = QMenu()
        menu.setObjectName("TrayMenu")

        # Заголовок меню — состояние обхода. Пункт неактивен: это подпись,
        # а не действие, но именно её читают первой.
        self._status_action = QAction("Состояние неизвестно", menu)
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)

        self._strategy_action = QAction("", menu)
        self._strategy_action.setEnabled(False)
        self._strategy_action.setVisible(False)
        menu.addAction(self._strategy_action)

        menu.addSeparator()

        self._toggle_action = QAction("Включить обход", menu)
        self._toggle_action.triggered.connect(controller.toggle)
        menu.addAction(self._toggle_action)

        # Избранные стратегии — чтобы переключиться, не открывая окно.
        self._favorites_menu = menu.addMenu("Стратегия")
        self._favorites_menu.menuAction().setVisible(False)

        menu.addSeparator()

        show_action = QAction("Открыть окно", menu)
        show_action.triggered.connect(self.show_requested.emit)
        menu.addAction(show_action)

        quit_action = QAction("Выход", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        controller.status_changed.connect(self.apply_status)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Одиночный щелчок левой кнопкой открывает окно: двойной тут непривычен,
        # потому что правая кнопка и так занята меню.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    def _rebuild_favorites(self, active: str) -> None:
        """Собирает подменю избранного заново — список мог измениться."""
        favorites = self.controller.settings.favorites
        self._favorites_menu.clear()
        self._favorites_menu.menuAction().setVisible(bool(favorites))

        for name in favorites:
            action = QAction(name, self._favorites_menu)
            action.setCheckable(True)
            action.setChecked(name == active)
            action.triggered.connect(lambda _, chosen=name: self._switch_to(chosen))
            self._favorites_menu.addAction(action)

    def _switch_to(self, name: str) -> None:
        self.controller.select_strategy(name)
        if self.controller.status.is_active:
            self.controller.restart()

    def apply_status(self, status: Status) -> None:
        self.setIcon(build_icon(status.is_active))
        self._toggle_action.setText("Выключить обход" if status.is_active else "Включить обход")
        self._toggle_action.setEnabled(status.core_present)

        self._status_action.setText(status.state_label.capitalize())

        strategy = status.active_strategy or status.selected_strategy
        self._strategy_action.setVisible(bool(strategy))
        self._strategy_action.setText(f"Стратегия: {strategy}" if strategy else "")

        self._rebuild_favorites(strategy)

        # Подсказка короткая: Windows показывает её крупной плашкой у курсора,
        # и название стратегии растягивало её на пол-экрана. Подробности и так
        # видны в самом меню.
        self.setToolTip(f"ZapretXmel — {status.state_label}")
