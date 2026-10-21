"""Значок в системном трее.

Оформления два, и выбирает человек. У обоих значок рисуется в коде одинаково —
логотип, кружки состояния в углу и отметка, — а отличается только логотип:
«классика» берёт полный, «современный» — упрощённый из `assets/tray-logo.png`,
растянутый на весь кадр. Спор тут не разрешить за пользователя: первый
вариант узнаваем, второй читается в шестнадцати пикселях, и каждому важно своё.

Поверх состояния значок может нести отметку: кружок со стрелкой вверх —
есть обновление, восклицательный знак — сторож заметил, что обход перестал
работать. Обе вещи программа и так знает, но узнать о них можно было только
открыв окно, а в трей её сворачивают именно чтобы не открывать.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from app.core import paths
from app.ui.controller import Controller, Status
from app.ui.theme.tokens import BRAND, COLORS
from app.ui.widgets import logo_pixmap

log = logging.getLogger(__name__)

# Размеры, в которых рисуется значок. Трей просит шестнадцать или тридцать
# два пикселя, а при масштабе системы — больше; готовый рисунок под каждый
# лучше, чем один, сжатый на лету.
ICON_SIZES = (16, 20, 24, 32, 48, 64, 128)

# Цвет обводки отметки — тот же почти чёрный, что у контура самого логотипа.
OUTLINE = "#16161a"

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

    Устроено у обоих одинаково — логотип, кружки состояния в углу и отметка, —
    различается только сам логотип. «Классика» берёт полный, тот же, что на
    панели задач. «Современный» берёт упрощённый: без тонкой обводки и мелких
    деталей, которые в шестнадцати пикселях сливаются в кашу, и растянутый на
    весь кадр — в трее значок и так крошечный, а пустое поле вокруг отнимает у
    него ещё несколько пикселей.

    Выбор за человеком, потому что спорно: одному важнее узнаваемость,
    другому — различимость на глаз в мелком размере.
    """
    if style == "modern":
        logo = _modern_logo()
        if logo is not None:
            return _compose(lambda size: logo, True, active, proxy, badge)
        # Картинки нет (старая установка, обрезанная сборка) — молча рисуем
        # классику: значок трея слишком мелкая вещь, чтобы из-за неё ругаться.
        log.debug("Упрощённый логотип не найден, рисую классику")

    return _compose(logo_pixmap, False, active, proxy, badge)


def _modern_logo() -> QPixmap | None:
    """Упрощённый логотип из `assets/tray-logo.png`; None — если его нет."""
    path = paths.tray_logo_file()
    if not path.exists():
        return None
    pixmap = QPixmap(str(path))
    return None if pixmap.isNull() else pixmap


def _compose(logo_for, fill: bool, active: bool, proxy: bool, badge: str) -> QIcon:
    """Собирает значок во всех размерах, которые может запросить трей.

    Отдельный рисунок на каждый размер, а не один, сжатый системой: толщина
    обводки кружков и отметки считается от размера, и сжатая картинка давала
    бы на шестнадцати пикселях размытую кашу.
    """
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(_paint(size, logo_for(size), fill, active, proxy, badge))
    return icon


def _paint(
    size: int, logo: QPixmap, fill: bool, active: bool, proxy: bool, badge: str
) -> QPixmap:
    """Один размер. Все длины — доли от размера, опорный кадр — 64 пикселя.

    Точка рисуется только на то, что работает: зелёная — обход, голубая —
    прокси для Telegram. Серая точка значит, что не работает ничего, и
    поэтому она одна: серый кружок рядом с голубым читался как «что-то
    сломано», хотя сломанного нет.

    Когда не работает ничего, логотип ещё и приглушается: значок остаётся
    узнаваемым, но не притворяется работающим.
    """
    k = size / 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    if logo.isNull():
        painter.setPen(QPen(QColor(COLORS["text_dim"]), 6 * k))
        painter.drawEllipse(QRectF(10 * k, 10 * k, size - 20 * k, size - 20 * k))
    else:
        if not (active or proxy):
            painter.setOpacity(0.45)
        if fill:
            painter.drawPixmap(QRectF(0, 0, size, size), logo, QRectF(logo.rect()))
        else:
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
    dot = 24.0 * k
    painter.setPen(QPen(QColor(COLORS["bg"]), 4 * k))
    for index, colour in enumerate(reversed(dots)):
        painter.setBrush(QColor(colour))
        left = size - dot - 1 * k - index * (dot + 4 * k)
        painter.drawEllipse(QRectF(left, size - dot - 2 * k, dot, dot))

    if badge in ("update", "alert"):
        _paint_badge(painter, size, k, badge)

    painter.end()
    return pixmap


def _paint_badge(painter: QPainter, size: int, k: float, badge: str) -> None:
    """Отметка в правом верхнем углу: стрелка вверх или восклицательный знак.

    Углы заняты по смыслу: снизу то, что работает сейчас, сверху — то, что
    требует внимания. Рисуется путями, а не символом шрифта: у глифов свои
    поля, из-за которых они садятся в круге мимо центра.
    """
    diameter = 26.0 * k
    box = QRectF(size - diameter - 1 * k, 1 * k, diameter, diameter)
    centre = box.center()
    radius = diameter / 2

    # Тревога красная, обновление белое: по цвету их различить проще, чем по
    # символу, который в шестнадцати пикселях — всего несколько точек.
    alert = badge == "alert"
    # Обводка тёмная всегда, а не цвета темы приложения: трей рисуется на панели
    # задач Windows, и её тема с темой приложения не связана. Белый круг со
    # светлой обводкой на светлой панели пропал бы вместе с рисунком.
    painter.setPen(QPen(QColor(OUTLINE), 3 * k))
    painter.setBrush(QColor(COLORS["danger"] if alert else "#ffffff"))
    painter.drawEllipse(box)

    ink = QColor("#ffffff" if alert else OUTLINE)
    if alert:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        stem = QRectF(centre.x() - 0.14 * radius, centre.y() - 0.62 * radius,
                      0.28 * radius, 0.74 * radius)
        painter.drawRoundedRect(stem, 0.12 * radius, 0.12 * radius)
        dot = 0.17 * radius
        painter.drawEllipse(QPointF(centre.x(), centre.y() + 0.54 * radius), dot, dot)
        return

    # Стрелка вверх. Круговая стрелка «обновить» в шестнадцати пикселях сливается
    # в кольцо и читается как часы, а толстая стрелка вверх узнаётся при любом
    # размере: наконечник и ножка — всего две простые фигуры.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ink)
    painter.drawPolygon(QPolygonF([
        QPointF(centre.x(), centre.y() - 0.66 * radius),
        QPointF(centre.x() - 0.54 * radius, centre.y() - 0.02 * radius),
        QPointF(centre.x() + 0.54 * radius, centre.y() - 0.02 * radius),
    ]))
    painter.drawRect(QRectF(centre.x() - 0.18 * radius, centre.y() - 0.08 * radius,
                            0.36 * radius, 0.7 * radius))


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
