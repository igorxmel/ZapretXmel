"""Детали экрана стратегий: строки списка и разбор секций.

Экран был стеной моноширинного текста: двадцать два почти одинаковых имени и сырые строки
аргументов. Здесь цвет несёт смысл, а не украшает: процент стабильности — зелёный, жёлтый
или красный, TCP и UDP различаются с одного взгляда. Остальное — обычным текстом: когда
цветной была каждая таблетка, секция читалась радугой и смысл цвета терялся.
"""

from __future__ import annotations

import html
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
    QWidget,
    QWidgetItem,
)

from app.core.batfile import Section
from app.ui.theme.tokens import BRAND, COLORS, RADIUS, SPACE

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
    """Строка списка: общее «general» приглушено, отличие — ярко, за ним процент.

    Двадцать две строки «general (ALTn)» читались как одна: глазу не за что зацепиться.
    Процент стоит сразу за именем, а не у правого края: в широком окне между ними
    оставалось полэкрана, и было не понять, к какой строке он относится.
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

        # Сначала меряем отметку: имени достаётся то, что останется рядом с ней.
        small = QFont(font)
        small.setPointSizeF(max(7.0, font.pointSizeF() - 1))
        mark = self._mark(index, QFontMetrics(small))
        limit = rect.right() - SPACE["sm"]
        room = limit - x - (mark[1] + SPACE["sm"] if mark else 0)

        base, tail = split_name(name)
        metrics = QFontMetrics(font)
        if base:
            painter.setFont(font)
            painter.setPen(QColor(COLORS["text_muted"]))
            text = base + " "
            painter.drawText(QRectF(x, rect.top(), max(0.0, room), rect.height()),
                             Qt.AlignmentFlag.AlignVCenter, text)
            advance = metrics.horizontalAdvance(text)
            x += advance
            room -= advance
        strong = QFont(font)
        strong.setWeight(QFont.Weight.DemiBold)
        painter.setFont(strong)
        broken = bool(index.data(BROKEN_ROLE))
        painter.setPen(QColor(COLORS["danger"] if broken else COLORS["text"]))
        strong_metrics = QFontMetrics(strong)
        shown = strong_metrics.elidedText(tail, Qt.TextElideMode.ElideRight, int(max(0, room)))
        painter.drawText(QRectF(x, rect.top(), max(0.0, room), rect.height()),
                         Qt.AlignmentFlag.AlignVCenter, shown)
        x += strong_metrics.horizontalAdvance(shown)

        if mark:
            painter.setFont(small)
            self._paint_mark(painter, mark, x + SPACE["sm"], rect)
        painter.restore()

    @staticmethod
    def _mark(index, metrics: QFontMetrics) -> tuple[str, float, str, bool] | None:
        """Текст отметки, её ширина, цвет и таблетка ли это."""
        if index.data(BROKEN_ROLE):
            text = "не запускается"
            return text, metrics.horizontalAdvance(text), COLORS["danger"], False
        percent = index.data(PERCENT_ROLE)
        if percent is None:
            return None
        text = f"{percent}%"
        width = metrics.horizontalAdvance(text) + SPACE["md"]
        return text, width, rate_colour(int(percent)), True

    @staticmethod
    def _paint_mark(painter, mark, left: float, rect: QRectF) -> None:
        text, width, colour, boxed = mark
        if not boxed:
            painter.setPen(QColor(colour))
            painter.drawText(QRectF(left, rect.top(), width, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter, text)
            return
        height = painter.fontMetrics().height() + 4
        pill = QRectF(left, rect.center().y() - height / 2, width, height)
        path = QPainterPath()
        path.addRoundedRect(pill, height / 2, height / 2)
        fill = QColor(colour)
        fill.setAlpha(38)
        painter.fillPath(path, fill)
        painter.setPen(QColor(colour))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)


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


# --- секции ----------------------------------------------------------------------


def section_html(section: Section) -> str:
    """«TCP 80,443 · обход fake, multisplit · списки list-general».

    Цвет — только у протокола: его и ищут глазами. Подписи «обход» и «списки»
    приглушены, чтобы значения читались первыми.
    """
    muted = COLORS["text_muted"]
    dim = COLORS["text_dim"]

    def label(text: str) -> str:
        return f'<span style="color:{muted}">{text}</span> '

    protocols = []
    for protocol, ports in section.protocols:
        colour = COLORS["tcp"] if protocol == "TCP" else COLORS["udp"]
        head = f'<span style="color:{colour}; font-weight:600">{protocol}</span>'
        protocols.append(f"{head} {html.escape(ports)}" if ports else head)
    parts = [", ".join(protocols) or label("весь трафик").strip()]
    if section.methods:
        parts.append(label("обход") + html.escape(", ".join(section.methods)))
    if section.list_names:
        # Неразрывный дефис: перенос резал «list-general-user» на две строки.
        names = html.escape(", ".join(section.list_names)).replace("-", "\u2011")
        parts.append(label("списки") + f'<span style="color:{dim}">{names}</span>')
    gap = f'<span style="color:{muted}">&nbsp;&nbsp;·&nbsp;&nbsp;</span>'
    return gap.join(parts)


class SectionRow(QFrame):
    """Одна секция строкой: номер и разбор, оба по центру строки."""

    def __init__(self, number: int, section: Section, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SectionRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE["sm"], SPACE["xs"] + 2, SPACE["md"], SPACE["xs"] + 2)
        row.setSpacing(SPACE["md"])

        badge = QLabel(str(number))
        badge.setObjectName("SectionNumber")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(22, 22)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

        self.text = QLabel(section_html(section))
        self.text.setObjectName("SectionText")
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setWordWrap(True)
        self.text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(self.text, 1, Qt.AlignmentFlag.AlignVCenter)
        self.setToolTip(section.describe())
