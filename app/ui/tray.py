"""Значок в системном трее.

Оформления два, и выбирает человек. «Классика» рисуется в коде — логотип и
точки состояния в углу; «современный» берёт готовые картинки из `assets/tray`,
где цветом залит весь значок. Спор тут не разрешить за пользователя: первый
вариант узнаваем, второй различим в шестнадцати пикселях, и каждому важно своё.

Поверх состояния значок может нести отметку: кружок с круговой стрелкой —
есть обновление, восклицательный знак — сторож заметил, что обход перестал
работать. Обе вещи программа и так знает, но узнать о них можно было только
открыв окно, а в трей её сворачивают именно чтобы не открывать.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from app.core import paths
from app.ui.controller import Controller, Status
from app.ui.theme.tokens import BRAND, COLORS
from app.ui.widgets import logo_pixmap

log = logging.getLogger(__name__)

# Оформления значка: подпись для человека — значение для настроек. Порядок
# тот же, что в выпадающем списке, поэтому словарь, а не две константы.
STYLES: dict[str, str] = {
    "Классика": "classic",
    "Современный": "modern",
}


def app_icon() -> QIcon:
    """Значок приложения — логотип, если он на месте."""
    pixmap = logo_pixmap(256)
    return QIcon(pixmap) if not pixmap.isNull() else QIcon()


def choose_badge(has_alert: bool, has_update: bool) -> str:
    """Какую отметку показать, когда их просится сразу две.

    Тревога важнее обновления: обход, который не работает, — причина, по
    которой программу открывают, а новая версия подождёт до вечера.
    """
    if has_alert:
        return "alert"
    return "update" if has_update else ""


def build_icon(
    active: bool,
    proxy: bool = False,
    style: str = "classic",
    badge: str = "",
) -> QIcon:
    """Значок для трея в выбранном оформлении.

    Стилей два, и они решают разные задачи. «Классика» рисуется на месте:
    логотип и точки состояния в углу — значок остаётся узнаваемым тем же,
    что на панели задач. «Современный» — готовые картинки, где цветом залит
    весь значок: в трее он показывается в шестнадцать пикселей, и пятно
    целиком читается там, где точка в углу уже не видна.

    Выбор за человеком, потому что спорно: одному важнее узнаваемость,
    другому — различимость на глаз в мелком размере.
    """
    if style == "modern":
        icon = _modern_icon(active, proxy, badge)
        if icon is not None:
            return icon
        # Набора нет (старая установка, обрезанная сборка) — молча рисуем
        # классику: значок трея слишком мелкая вещь, чтобы из-за неё ругаться.
        log.debug("Набор значков «современный» не найден, рисую классику")

    return _classic_icon(active, proxy)


def _modern_icon(active: bool, proxy: bool, badge: str) -> QIcon | None:
    """Готовая картинка из набора; None — если набора нет."""
    if active and proxy:
        state = "both"
    elif active:
        state = "bypass"
    elif proxy:
        state = "telegram"
    else:
        state = "off"

    suffix = f"-{badge}" if badge in ("update", "alert") else ""
    path = paths.tray_icon_file(f"{state}{suffix}")
    if not path.exists():
        return None

    pixmap = QPixmap(str(path))
    return QIcon(pixmap) if not pixmap.isNull() else None


def _classic_icon(active: bool, proxy: bool = False) -> QIcon:
    """Значок для трея: логотип и точки состояния в углу.

    Точка рисуется только на то, что работает: зелёная — обход, голубая —
    прокси для Telegram. Серая точка значит, что не работает ничего, и
    поэтому она одна: серый кружок рядом с голубым читался как «что-то
    сломано», хотя сломанного нет.

    Когда не работает ничего, логотип ещё и приглушается: значок остаётся
    узнаваемым, но не притворяется работающим.
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
        if not (active or proxy):
            painter.setOpacity(0.45)
        painter.drawPixmap(0, 0, logo)
        painter.setOpacity(1.0)

    # Порядок тот же, что у кнопок на главном экране: сначала обход, потом
    # Telegram. В трее они стояли наоборот, и значок читался задом наперёд.
    dots = []
    if active:
        dots.append(COLORS["success"])
    if proxy:
        dots.append(BRAND["telegram"])
    if not dots:
        dots.append(COLORS["text_muted"])

    # Крупнее: в трее значок уменьшается до 16 пикселей, и прежние
    # точки превращались в неразличимые крапинки.
    dot = 24.0
    painter.setPen(QPen(QColor(COLORS["bg"]), 4))
    for index, colour in enumerate(reversed(dots)):
        painter.setBrush(QColor(colour))
        left = size - dot - 1 - index * (dot + 4)
        painter.drawEllipse(QRectF(left, size - dot - 2, dot, dot))

    painter.end()

    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    """Управление обходом, не открывая окно."""

    show_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller

        # Последнее известное состояние: отметки приходят не вместе с ним, а
        # когда случатся, и перерисовать значок надо, ничего не потеряв.
        self._active = False
        self._proxy = False
        # Два независимых признака, а не одно поле «какая отметка». С одним
        # полем приходилось решать приоритет прямо в месте записи, и тогда
        # прошедшая проверка сторожа не могла снять тревогу, не затерев
        # заодно обновление.
        self._has_update = False
        self._has_alert = False

        self.setIcon(self._icon())
        self.setToolTip("ZapretXmel")

        menu = QMenu()
        menu.setObjectName("TrayMenu")

        # Заголовок меню — состояние обхода. Пункт неактивен: это подпись,
        # а не действие, но именно её читают первой.
        self._status_action = QAction("Состояние неизвестно", menu)
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)

        self._proxy_status_action = QAction("", menu)
        self._proxy_status_action.setEnabled(False)
        self._proxy_status_action.setVisible(False)
        menu.addAction(self._proxy_status_action)

        self._strategy_action = QAction("", menu)
        self._strategy_action.setEnabled(False)
        self._strategy_action.setVisible(False)
        menu.addAction(self._strategy_action)

        menu.addSeparator()

        self._toggle_action = QAction("Включить обход", menu)
        self._toggle_action.triggered.connect(controller.toggle)
        menu.addAction(self._toggle_action)

        self._proxy_action = QAction("Включить прокси для Telegram", menu)
        self._proxy_action.triggered.connect(controller.toggle_telegram)
        menu.addAction(self._proxy_action)

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

    def _icon(self) -> QIcon:
        return build_icon(
            self._active,
            self._proxy,
            style=self.controller.settings.tray_style,
            badge=choose_badge(self._has_alert, self._has_update),
        )

    def set_update(self, found: bool) -> None:
        """Есть ли обновление — программы, ядра или прокси."""
        self._has_update = found
        self.setIcon(self._icon())

    def set_alert(self, broken: bool) -> None:
        """Заметил ли сторож, что обход перестал работать."""
        self._has_alert = broken
        self.setIcon(self._icon())

    def refresh_style(self) -> None:
        """Перерисовывает значок после смены оформления в настройках."""
        self.setIcon(self._icon())

    def apply_status(self, status: Status) -> None:
        self._active = status.is_active
        self._proxy = status.telegram_running
        self.setIcon(self._icon())
        self._toggle_action.setText("Выключить обход" if status.is_active else "Включить обход")
        self._toggle_action.setEnabled(status.core_present)

        self._status_action.setText(status.state_label.capitalize())

        self._proxy_status_action.setVisible(status.telegram_installed)
        self._proxy_status_action.setText(
            "Прокси Telegram: работает" if status.telegram_running else "Прокси Telegram: выключен"
        )
        self._proxy_action.setEnabled(status.telegram_installed)
        self._proxy_action.setText(
            "Выключить прокси для Telegram"
            if status.telegram_running
            else "Включить прокси для Telegram"
        )

        strategy = status.active_strategy or status.selected_strategy
        self._strategy_action.setVisible(bool(strategy))
        self._strategy_action.setText(f"Стратегия: {strategy}" if strategy else "")

        self._rebuild_favorites(strategy)

        # Подсказка короткая: Windows показывает её крупной плашкой у курсора,
        # и название стратегии растягивало её на пол-экрана. Подробности и так
        # видны в самом меню.
        self.setToolTip(f"ZapretXmel — {status.state_label}")
