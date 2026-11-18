"""Детали экрана стратегий: строки списка, плитки сводки и разбор секций.

Экран был стеной моноширинного текста: двадцать два почти одинаковых имени и сырые строки
аргументов. Здесь цвет несёт смысл, а не украшает: процент стабильности — зелёный, жёлтый
или красный, TCP и UDP различаются с одного взгляда, способы обхода и списки — таблетками.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QModelIndex, QPoint, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from app.core.batfile import Section
from app.ui.theme.tokens import BRAND, COLORS, FONT_SIZE, RADIUS, SPACE, is_light

NAME_ROLE = Qt.ItemDataRole.UserRole
PERCENT_ROLE = Qt.ItemDataRole.UserRole + 1
STATE_ROLE = Qt.ItemDataRole.UserRole + 2
FAVORITE_ROLE = Qt.ItemDataRole.UserRole + 3
BROKEN_ROLE = Qt.ItemDataRole.UserRole + 4

_TAIL = re.compile(r"^(.*?)\s*\((.+)\)$")


def split_name(name: str) -> tuple[str, str]:
    """«general (ALT13)» → ("general", "ALT13"). Своё имя без скобок — целиком главное."""
    match = _TAIL.match(name)
    return (match.group(1), match.group(2)) if match else ("", name)


def rate_colour(percent: int) -> str:
    """Зелёный — держит, жёлтый — через раз, красный — лучше не брать."""
    if percent >= 90:
        return COLORS["success"]
    if percent >= 70:
        return COLORS["warning"]
    return COLORS["danger"]


def tinted(colour: str, alpha: int) -> str:
    """Цвет с прозрачностью для фона таблетки: «rgba(…)» для таблицы стилей."""
    value = QColor(colour)
    return f"rgba({value.red()}, {value.green()}, {value.blue()}, {alpha})"


# --- список стратегий ------------------------------------------------------------


class StrategyDelegate(QStyledItemDelegate):
    """Строка списка: общее «general» приглушено, отличие — ярко, справа процент.

    Двадцать две строки «general (ALTn)» читались как одна: глазу не за что зацепиться.
    """

    HEIGHT = 34

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), self.HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            path = QPainterPath()
            path.addRoundedRect(rect, RADIUS["md"], RADIUS["md"])
            painter.fillPath(
                path, QColor(COLORS["elevated"] if selected else COLORS["surface_hover"])
            )
            if selected:
                painter.setPen(QColor(COLORS["border_strong"]))
                painter.drawPath(path)

        name = index.data(NAME_ROLE) or ""
        state = index.data(STATE_ROLE) or ""
        x = rect.left() + SPACE["md"]
        middle = rect.center().y()

        # Точка состояния: зелёная — работает сейчас, кольцо — выбрана, но выключена.
        dot = 7
        if state == "active":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["success"]))
            painter.drawEllipse(QRectF(x, middle - dot / 2, dot, dot))
        elif state == "selected":
            painter.setPen(QColor(COLORS["text_dim"]))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(x + 0.5, middle - dot / 2 + 0.5, dot - 1, dot - 1))
        x += dot + SPACE["sm"]

        font = QFont(option.font)
        if index.data(FAVORITE_ROLE):
            painter.setPen(QColor(BRAND["orange"]))
            painter.setFont(font)
            star = "★"
            painter.drawText(QRectF(x, rect.top(), 16, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter, star)
            x += QFontMetrics(font).horizontalAdvance(star) + SPACE["xs"]

        # Справа — сначала отметки, чтобы имя знало, сколько места осталось.
        right = rect.right() - SPACE["sm"]
        right = self._paint_marks(painter, index, font, right, rect)

        base, tail = split_name(name)
        metrics = QFontMetrics(font)
        if base:
            painter.setFont(font)
            painter.setPen(QColor(COLORS["text_muted"]))
            text = base + " "
            painter.drawText(QRectF(x, rect.top(), right - x, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter, text)
            x += metrics.horizontalAdvance(text)
        strong = QFont(font)
        strong.setWeight(QFont.Weight.DemiBold)
        painter.setFont(strong)
        broken = bool(index.data(BROKEN_ROLE))
        painter.setPen(QColor(COLORS["danger"] if broken else COLORS["text"]))
        shown = QFontMetrics(strong).elidedText(tail, Qt.TextElideMode.ElideRight, int(right - x))
        painter.drawText(QRectF(x, rect.top(), right - x, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter, shown)
        painter.restore()

    @staticmethod
    def _paint_marks(painter, index, font, right: float, rect: QRectF) -> float:
        small = QFont(font)
        small.setPointSizeF(max(7.0, font.pointSizeF() - 1))
        metrics = QFontMetrics(small)
        painter.setFont(small)

        if index.data(BROKEN_ROLE):
            text = "не запускается"
            width = metrics.horizontalAdvance(text)
            painter.setPen(QColor(COLORS["danger"]))
            painter.drawText(QRectF(right - width, rect.top(), width, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter, text)
            return right - width - SPACE["md"]

        percent = index.data(PERCENT_ROLE)
        if percent is None:
            return right
        text = f"{percent}%"
        width = metrics.horizontalAdvance(text) + SPACE["md"]
        height = metrics.height() + 4
        pill = QRectF(right - width, rect.center().y() - height / 2, width, height)
        colour = rate_colour(int(percent))
        path = QPainterPath()
        path.addRoundedRect(pill, height / 2, height / 2)
        fill = QColor(colour)
        fill.setAlpha(38)
        painter.fillPath(path, fill)
        painter.setPen(QColor(colour))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        return pill.left() - SPACE["md"]


# --- раскладка «в поток» ---------------------------------------------------------


class FlowLayout(QLayout):
    """Ряд, который переносит элементы на новую строку, когда не хватает ширины.

    Таблетки в строку уезжали за край карточки, и появлялась горизонтальная прокрутка.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = SPACE["xs"] + 1):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 — имя задано Qt
        self._items.append(item)

    def addWidget(self, widget: QWidget) -> None:  # noqa: N802 — имя задано Qt
        self.addChildWidget(widget)
        self.addItem(QWidgetItem(widget))

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect: QRect, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x = rect.x()
                y += line + self._gap
                line = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        return y + line - rect.y()


def pill(text: str, colour: str, *, mono: bool = False, strong: bool = False) -> QLabel:
    """Таблетка с текстом цвета `colour` на его же полупрозрачном фоне."""
    label = QLabel(text)
    family = "font-family: 'Cascadia Mono', Consolas, monospace;" if mono else ""
    weight = "font-weight: 600;" if strong else ""
    label.setStyleSheet(
        f"color: {colour}; background: {tinted(colour, 34)};"
        f"border-radius: {RADIUS['sm']}px; padding: 1px {SPACE['sm']}px;"
        f"font-size: {FONT_SIZE['caption']}px; {family} {weight}"
    )
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return label


# --- сводка ----------------------------------------------------------------------


class Tile(QFrame):
    """Плитка сводки: крупное значение и подпись под ним."""

    def __init__(self, caption: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StatTile")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        layout.setSpacing(0)
        self.value = QLabel("—")
        self.value.setObjectName("StatValue")
        layout.addWidget(self.value)
        self.caption = QLabel(caption)
        self.caption.setObjectName("Muted")
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)

    def show_value(self, value: str, caption: str = "", colour: str = "") -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color: {colour};" if colour else "")
        if caption:
            self.caption.setText(caption)


# --- секции ----------------------------------------------------------------------


class SectionRow(QFrame):
    """Одна секция: номер, протоколы с портами, способы обхода, списки."""

    def __init__(self, number: int, section: Section, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SectionRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE["sm"], SPACE["sm"], SPACE["sm"], SPACE["sm"])
        row.setSpacing(SPACE["md"])

        badge = QLabel(str(number))
        badge.setObjectName("SectionNumber")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(22, 22)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        flow_box = QWidget()
        flow_box.setObjectName("Flow")
        flow = FlowLayout(flow_box)
        for protocol, ports in section.protocols or [("ВСЁ", "")]:
            colour = COLORS["tcp"] if protocol == "TCP" else COLORS["udp"]
            flow.addWidget(pill(protocol, colour, strong=True))
            if ports:
                flow.addWidget(pill(ports, COLORS["text_dim"]))
        # Фирменный оранжевый на светлом фоне не читается — там он темнее.
        method_colour = "#a35400" if is_light() else BRAND["orange"]
        for method in section.methods:
            flow.addWidget(pill(method, method_colour))
        for name in section.list_names:
            flow.addWidget(pill(f"▤ {name}", COLORS["success"]))
        flow_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(flow_box, 1)
        self.setToolTip(section.describe())
