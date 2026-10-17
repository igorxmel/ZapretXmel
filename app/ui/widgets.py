"""Собственные виджеты.

То, чего нет в стандартном наборе Qt и что задаёт узнаваемый вид приложения:
индикатор состояния, круглая кнопка включения и бейдж исхода пробы. Рисуются
через QPainter — собрать их из готовых контролов со стилями не получилось бы
без лишних обёрток.
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QIcon, QPainter, QPaintEvent, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStyle,
    QStyleOption,
    QVBoxLayout,
    QWidget,
)

from app.ui import motion
from app.ui.theme.tokens import BRAND, COLORS, FONT_SIZE, SPACE


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


# Длительности анимаций. Короткие нарочно: движение должно подсказывать, что
# состояние сменилось, а не заставлять себя ждать — по кнопке и по пунктам
# меню щёлкают часто и быстро.
RING_FILL_MS = 460
PILL_FADE_MS = 220
NAV_SLIDE_MS = 240

# Ширина оранжевой полоски у выбранного пункта меню.
NAV_MARK_WIDTH = 2.0


def _blend(start: QColor, end: QColor, ratio: float) -> QColor:
    """Цвет между двумя по доле `ratio` от 0 до 1."""
    ratio = max(0.0, min(1.0, ratio))
    return QColor(
        round(start.red() + (end.red() - start.red()) * ratio),
        round(start.green() + (end.green() - start.green()) * ratio),
        round(start.blue() + (end.blue() - start.blue()) * ratio),
    )


class WheelGuard(QObject):
    """Не даёт колесу мыши менять значения при прокрутке страницы.

    Настройки длиннее экрана, их прокручивают — и курсор по дороге проходит
    над списками и счётчиками. Qt отдаёт колесо тому, что под курсором, и
    человек, листая страницу, незаметно менял таймаут проверки или выбранную
    стратегию.

    Колесо работает, только когда поле выбрано щелчком: тогда это уже
    осознанное действие, а не прокрутка мимо.
    """

    GUARDED = (QComboBox, QSpinBox, QSlider)

    def eventFilter(self, target, event) -> bool:  # noqa: N802 — имя задано Qt
        if (
            event.type() == QEvent.Type.Wheel
            and isinstance(target, self.GUARDED)
            and not target.hasFocus()
        ):
            # Событие не глотаем, а передаём выше — прокручивается страница.
            event.ignore()
            return True
        return super().eventFilter(target, event)


class Sidebar(QWidget):
    """Боковое меню, которое само рисует полоску у выбранного пункта.

    Полоска была отдельным виджетом и ездила между пунктами, двигая себя.
    Каждый кадр при этом перерисовывались и она, и открывшийся из-под неё
    кусок кнопки, а положение считалось целыми пикселями — движение
    получалось дёрганым, особенно на коротких переходах.

    Здесь она часть самой панели: один проход отрисовки на кадр и дробная
    координата, так что сглаживание доводит движение до плавного.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._mark_y = 0.0
        self._mark_height = 0.0
        self._mark_shown = False

    def set_mark_height(self, height: float) -> None:
        self._mark_height = height
        self._mark_shown = True
        self.update()

    def get_mark_y(self) -> float:
        return self._mark_y

    def set_mark_y(self, value: float) -> None:
        self._mark_y = value
        self.update()

    mark_y = pyqtProperty(float, fget=get_mark_y, fset=set_mark_y)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя задано Qt
        """Рисует фон из таблицы стилей, а поверх — полоску.

        Подклассам QWidget Qt оформление из QSS сам не рисует: без явной
        отрисовки подложки у панели пропали бы и фон, и правая граница.
        """
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_Widget, option, painter, self
        )

        if not self._mark_shown or self._mark_height <= 0:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BRAND["orange"]))
        painter.drawRect(QRectF(0.0, self._mark_y, NAV_MARK_WIDTH, self._mark_height))


class StatusPill(QWidget):
    """Точка состояния с подписью.

    Цвет — единственное место в интерфейсе, где он несёт смысл: зелёный значит
    работает, красный — сломано, серый — выключено.
    """

    def __init__(self, text: str = "", color: str = COLORS["text_muted"], parent=None):
        super().__init__(parent)
        self._text = text
        self._color = QColor(color)
        self._from = QColor(color)
        self._target = QColor(color)
        self._shift = 1.0
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(20)

        self._fade = QPropertyAnimation(self, b"shift", self)
        self._fade.setDuration(PILL_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def set_state(self, text: str, color: str) -> None:
        """Подпись меняется сразу, цвет — переходом.

        Состояние опрашивается каждые несколько секунд, и мигание точки на
        каждом опросе читалось бы как тревога. Переход от текущего цвета,
        а не от прежнего состояния: опрос может застать анимацию на полпути.
        """
        self._text = text
        target = QColor(color)
        if target != self._target:
            self._from = QColor(self._color)
            self._target = target
            self._fade.stop()
            self._fade.setDuration(motion.duration(PILL_FADE_MS))
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()

        self.updateGeometry()
        self.update()

    def get_shift(self) -> float:
        return self._shift

    def set_shift(self, value: float) -> None:
        self._shift = value
        self._color = _blend(self._from, self._target, value)
        self.update()

    shift = pyqtProperty(float, fget=get_shift, fset=set_shift)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self._text) + 22, 20)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя задано Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        radius = 4.0
        center_y = self.height() / 2
        painter.setBrush(self._color)
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

    def __init__(self, parent: QWidget | None = None, accent: str = COLORS["success"]):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(116, 116)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._busy = False
        self._accent = QColor(accent)

        # Кольцо не перекрашивается рывком, а наливается цветом. Значение
        # анимации — от 0 (выключено) до 1 (работает).
        self._fill = 0.0
        self._settling = False
        self._available = True
        self._glow = QPropertyAnimation(self, b"fill", self)
        self._glow.setDuration(RING_FILL_MS)
        self._glow.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate_fill)

    def _animate_fill(self, on: bool) -> None:
        """Ведёт кольцо к новому состоянию от того, где оно сейчас.

        Отсчёт именно от текущего значения, а не от нуля: по кнопке щёлкают
        быстро и по многу раз, и анимация, начинающая каждый раз сначала,
        дёргала бы кольцо вместо того, чтобы доводить его до места.

        Пока кнопка занята, анимация не идёт: в это время кольцо нарисовано
        серым и перехода всё равно не видно. Включение службы занимает
        секунду-две, и переход успевал закончиться целиком за этой серой
        заглушкой — со стороны кольцо перекрашивалось рывком.
        """
        if self._busy:
            return

        self._glow.stop()
        self._glow.setDuration(motion.duration(RING_FILL_MS))
        self._glow.setStartValue(self._fill)
        self._glow.setEndValue(1.0 if on else 0.0)
        self._glow.start()

    def get_fill(self) -> float:
        return self._fill

    def set_fill(self, value: float) -> None:
        self._fill = value
        self.update()

    fill = pyqtProperty(float, fget=get_fill, fset=set_fill)

    def set_available(self, value: bool) -> None:
        """Можно ли нажимать вообще — без оглядки на идущий переход.

        Разведено с `setEnabled` нарочно: состояние опрашивается каждые
        несколько секунд, и опрос, пришедший посреди перехода, иначе
        разблокировал бы кнопку раньше времени.
        """
        self._available = value
        self.setEnabled(value and not self._busy and not self._settling)

    def _settled(self) -> None:
        """Переход закончился — кнопку снова можно нажимать."""
        self._settling = False
        self.setEnabled(self._available and not self._busy)

    def set_busy(self, busy: bool) -> None:
        """Занятая кнопка нарисована серым; переход показываем после неё.

        Пока идёт переход, нажимать нельзя: по кнопке щёлкают быстро, а
        каждое нажатие — это включение или выключение обхода, то есть
        работа со службой. Нажатия, накопленные за секунду, выполнялись бы
        одно за другим, и состояние расходилось с тем, что видно.
        """
        was, self._busy = self._busy, busy
        self._settling = busy or self._settling
        self.setEnabled(self._available and not busy and not self._settling)

        if was and not busy:
            self._glow.stop()
            self._glow.finished.connect(self._settled, Qt.ConnectionType.UniqueConnection)
            # Начинаем с противоположного края: состояние уже сменилось,
            # пока кнопка была серой, и наливаться кольцу иначе неоткуда.
            self._fill = 0.0 if self.isChecked() else 1.0
            self._animate_fill(self.isChecked())

        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя задано Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._busy:
            ring = glyph = QColor(COLORS["text_muted"])
        else:
            ring = QColor(COLORS["border_strong"])
            glyph = _blend(QColor(COLORS["text_dim"]), QColor(COLORS["text"]), self._fill)

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

        # Кольцо не перекрашивается, а обводится: цветная дуга идёт от
        # двенадцати часов по часовой стрелке и доходит до полного круга.
        # Смена цвета на тёмном фоне почти не читается — а растущая дуга
        # видна сразу и объясняет, что состояние меняется прямо сейчас.
        if not self._busy and self._fill > 0.0:
            accent = QPen(self._accent, 2.5, cap=Qt.PenCapStyle.RoundCap)
            painter.setPen(accent)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(circle, 90 * 16, -round(360 * 16 * self._fill))

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
        # Высота — по содержимому и не меньше: при системном масштабе 125%
        # раскладка сжимала часть таблеток, и текст в них обрезался.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(self.sizeHint().height())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.value = value or text


def spinner_icon(angle: int, size: int = 14, bright: bool = False) -> QIcon:
    """Кружок загрузки для пункта бокового меню.

    Рисуется дугой через QPainter, а не символом из шрифта: у глифов свои
    поля, и крутящийся символ гуляет вокруг центра вместо того, чтобы
    вращаться на месте.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor(COLORS["text"] if bright else COLORS["text_dim"]), 2)
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

