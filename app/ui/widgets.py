"""Собственные виджеты.

То, чего нет в стандартном наборе Qt и что задаёт узнаваемый вид приложения:
индикатор состояния, круглая кнопка включения и бейдж исхода пробы. Рисуются
через QPainter — собрать их из готовых контролов со стилями не получилось бы
без лишних обёрток.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPaintEvent, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme.tokens import COLORS, FONT_SIZE, SPACE


class Card(QFrame):
    """Приподнятая поверхность с рамкой — основной контейнер для блоков."""

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        self._layout.setSpacing(SPACE["md"])

        if title:
            self._layout.addWidget(SectionTitle(title))

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget


class SectionTitle(QLabel):
    """Подзаголовок раздела — набран капителью, как рубрика."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text.upper(), parent)
        self.setObjectName("SectionTitle")


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)


class StatusPill(QWidget):
    """Точка состояния с подписью.

    Цвет — единственное место в интерфейсе, где он несёт смысл: зелёный значит
    работает, красный — сломано, серый — выключено.
    """

    def __init__(self, text: str = "", color: str = COLORS["text_muted"], parent=None):
        super().__init__(parent)
        self._text = text
        self._color = color
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(20)

    def set_state(self, text: str, color: str) -> None:
        self._text, self._color = text, color
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self._text) + 22, 20)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя задано Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        radius = 4.0
        center_y = self.height() / 2
        painter.setBrush(QColor(self._color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(1, center_y - radius, radius * 2, radius * 2))

        painter.setPen(QColor(COLORS["text"]))
        painter.drawText(
            QRectF(radius * 2 + 8, 0, self.width() - radius * 2 - 8, self.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._text,
        )
        painter.end()


class PowerButton(QAbstractButton):
    """Главный выключатель обхода.

    Кольцо вокруг знака питания показывает состояние: зелёное — включено,
    приглушённое — выключено, пунктирное — идёт переключение.

    Сам знак рисуется дугой и отрезком, а не символом из шрифта: у глифа
    собственные поля сверху и снизу, из-за которых он садится в круге заметно
    выше центра, и выровнять его средствами текста не получается.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(116, 116)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._busy = False

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.setEnabled(not busy)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя задано Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._busy:
            ring = glyph = QColor(COLORS["text_muted"])
        elif self.isChecked():
            ring, glyph = QColor(COLORS["success"]), QColor(COLORS["text"])
        else:
            ring, glyph = QColor(COLORS["border_strong"]), QColor(COLORS["text_dim"])

        if self.underMouse() and not self._busy:
            ring = ring.lighter(125)

        inset = 5.0
        circle = QRectF(inset, inset, self.width() - inset * 2, self.height() - inset * 2)

        painter.setBrush(QColor(COLORS["surface"]))
        pen = QPen(ring, 2.5)
        if self._busy:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawEllipse(circle)

        centre_x, centre_y = self.width() / 2, self.height() / 2
        radius = self.width() * 0.17

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(glyph, 3.0, cap=Qt.PenCapStyle.RoundCap))

        # Дуга с разрывом сверху: начинается на 120° и идёт на 300°,
        # углы Qt задаёт в шестнадцатых долях градуса.
        arc = QRectF(centre_x - radius, centre_y - radius, radius * 2, radius * 2)
        painter.drawArc(arc, 120 * 16, 300 * 16)

        # Вертикальный штрих от верхнего края дуги к центру.
        painter.drawLine(
            QPointF(centre_x, centre_y - radius * 1.45),
            QPointF(centre_x, centre_y - radius * 0.1),
        )
        painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        self.update()
        super().leaveEvent(event)


class KeyValueRow(QWidget):
    """Строка «подпись — значение» для сводок."""

    def __init__(self, key: str, value: str = "—", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["md"])

        self._key = QLabel(key)
        self._key.setObjectName("Dim")
        self._value = QLabel(value)
        self._value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(self._key)
        layout.addStretch(1)
        layout.addWidget(self._value)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_value_color(self, color: str) -> None:
        self._value.setStyleSheet(f"color: {color};")


class ClickableLabel(QLabel):
    """Ссылка-подпись, по которой можно щёлкнуть."""

    clicked = pyqtSignal()

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("Muted")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def view_header(title: str, subtitle: str = "") -> QWidget:
    """Шапка экрана: заголовок и поясняющая строка под ним."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(SPACE["xs"])

    heading = QLabel(title)
    heading.setObjectName("ViewTitle")
    layout.addWidget(heading)

    if subtitle:
        caption = QLabel(subtitle)
        caption.setObjectName("ViewSubtitle")
        caption.setWordWrap(True)
        layout.addWidget(caption)

    return container


class Chip(QPushButton):
    """Таблетка-переключатель для выбора режима."""

    def __init__(self, text: str, value: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("Chip")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.value = value or text


def spinner_icon(angle: int, size: int = 14) -> QIcon:
    """Кружок загрузки для пункта бокового меню.

    Рисуется дугой через QPainter, а не символом из шрифта: у глифов свои
    поля, и крутящийся символ гуляет вокруг центра вместо того, чтобы
    вращаться на месте.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor(COLORS["text_dim"]), 2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)

    inset = 2.0
    box = QRectF(inset, inset, size - inset * 2, size - inset * 2)
    # Углы в Qt — в шестнадцатых долях градуса, отсчёт против часовой.
    painter.drawArc(box, -angle * 16, 270 * 16)
    painter.end()

    return QIcon(pixmap)


def logo_pixmap(size: int) -> QPixmap:
    """Логотип приложения нужного размера; пустая картинка, если файла нет."""
    from app.core import paths

    path = paths.logo_file()
    if not path.exists():
        return QPixmap()

    return QPixmap(str(path)).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def banner_pixmap(width: int) -> QPixmap:
    """Логотип с надписью, вписанный в заданную ширину."""
    from app.core import paths

    path = paths.banner_file()
    if not path.exists():
        return QPixmap()

    return QPixmap(str(path)).scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)


def badge(text: str, color: str) -> QLabel:
    """Небольшая метка — исход пробы, состояние, пометка."""
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(
        f"color: {color};"
        f"border: 1px solid {color};"
        f"border-radius: 3px;"
        f"padding: 1px {SPACE['sm']}px;"
        f"font-size: {FONT_SIZE['caption']}px;"
    )
    return label

