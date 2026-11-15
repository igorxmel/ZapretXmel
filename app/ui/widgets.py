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
    QVariantAnimation,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
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
from app.ui.theme.tokens import BRAND, COLORS, FONT_SIZE, SPACE, is_light


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


def set_markdown(view, text: str) -> None:
    """Показывает размеченный текст и красит ссылки в оранжевый.

    Ни таблица стилей документа, ни палитра виджета для ссылок не работают:
    первая не доходит, потому что разметка превращается в текст с уже
    проставленным цветом, вторую перебивает таблица стилей приложения —
    `QTextBrowser` наследует `QTextEdit`, а правила для него есть. Поэтому
    красим прямо в документе, после того как текст разобран.

    Оранжевый — единственное место, где цвет не обозначает состояние. Но
    ссылка обязана отличаться от обычных слов, иначе её не найти: системный
    синий на тёмном фоне не виден вовсе.
    """
    view.document().setDefaultStyleSheet(f"code {{ color: {COLORS['text_dim']}; }}")
    view.setMarkdown(text)

    document = view.document()
    highlight = QTextCharFormat()
    highlight.setForeground(QColor(BRAND["orange"]))

    block = document.begin()
    while block.isValid():
        piece = block.begin()
        while not piece.atEnd():
            fragment = piece.fragment()
            if fragment.isValid() and fragment.charFormat().isAnchor():
                cursor = QTextCursor(document)
                cursor.setPosition(fragment.position())
                cursor.setPosition(
                    fragment.position() + fragment.length(),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                cursor.mergeCharFormat(highlight)
            piece += 1
        block = block.next()


class WheelGuard(QObject):
    """Колесо мыши листает страницу, а не меняет значения.

    Настройки длиннее экрана, их прокручивают — и курсор по дороге проходит
    над списками и счётчиками. Qt отдаёт колесо тому, что под курсором, и
    человек, листая страницу, незаметно менял таймаут проверки или выбранную
    стратегию.

    Значение колесом не меняется вовсе, даже если поле выбрано: проверка на
    «выбрано щелчком» не спасала — попасть по полю, а потом крутить дальше,
    получается само собой. Менять значение есть чем: щелчок, стрелки,
    клавиатура.
    """

    GUARDED = (QComboBox, QSpinBox, QDoubleSpinBox, QSlider, QAbstractSpinBox)

    def eventFilter(self, target, event) -> bool:  # noqa: N802 — имя задано Qt
        if event.type() != QEvent.Type.Wheel or not isinstance(target, self.GUARDED):
            return super().eventFilter(target, event)

        # Событие не глотаем, а передаём прокручиваемой области выше —
        # иначе страница замирала бы каждый раз, когда курсор проходит
        # над полем.
        area = self._scrollable(target)
        if area is not None:
            QApplication.sendEvent(area, event)
        return True

    @staticmethod
    def _scrollable(widget):
        """Ближайшая прокручиваемая область выше по дереву."""
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea) and not isinstance(
                parent, WheelGuard.GUARDED
            ):
                return parent.viewport()
            parent = parent.parentWidget()
        return None


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

    Кольцо вокруг знака питания показывает состояние: цветное — включено,
    приглушённое — выключено. Пока идёт переключение, кнопка не нажимается.

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
        self._paused = False

        # Кольцо не перекрашивается рывком, а наливается цветом. Значение
        # анимации — от 0 (выключено) до 1 (работает).
        self._fill = 0.0
        self._settling = False
        self._available = True
        self._glow = QPropertyAnimation(self, b"fill", self)
        self._glow.setDuration(RING_FILL_MS)
        self._glow.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate_fill)
        # Подключаем один раз здесь, а не при каждом переключении: PyQt на
        # повторное подключение с UniqueConnection бросает TypeError, и
        # вторая же смена состояния роняла программу.
        self._glow.finished.connect(self._settled)

        # Пауза обводится своей жёлтой дугой так же, как работа — зелёной.
        # Мгновенная перекраска выглядела как сбой, а не как смена состояния.
        self._hold = 0.0
        self._hold_anim = QPropertyAnimation(self, b"hold", self)
        self._hold_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    def _animate_fill(self, on: bool) -> None:
        """Ведёт кольцо к новому состоянию от того, где оно сейчас.

        Отсчёт именно от текущего значения, а не от края: по кнопке щёлкают
        быстро и по многу раз, и анимация, начинающая каждый раз сначала,
        дёргала бы кольцо вместо того, чтобы доводить его до места.

        Никаких промежуточных состояний у кольца нет — оно просто идёт к
        цели. Попытка показать «идёт переключение» отдельно оборачивалась
        морганием: кольцо гасло в серое, потом заливалось целиком и только
        потом сливалось обратно.
        """
        self._glow.stop()
        self._glow.setDuration(motion.duration(RING_FILL_MS))
        self._glow.setStartValue(self._fill)
        self._glow.setEndValue(1.0 if on else 0.0)

        # Пока кольцо идёт к цели, нажимать нельзя: каждое нажатие — это
        # работа со службой, и накопленные за секунду выполнялись бы одно
        # за другим, расходясь с тем, что видно.
        self._settling = True
        self._sync_enabled()
        self._glow.start()

    def get_fill(self) -> float:
        return self._fill

    def set_fill(self, value: float) -> None:
        self._fill = value
        self.update()

    fill = pyqtProperty(float, fget=get_fill, fset=set_fill)

    def get_hold(self) -> float:
        return self._hold

    def set_hold(self, value: float) -> None:
        self._hold = value
        self.update()

    hold = pyqtProperty(float, fget=get_hold, fset=set_hold)

    def set_available(self, value: bool) -> None:
        """Можно ли нажимать вообще — без оглядки на идущий переход."""
        self._available = value
        self._sync_enabled()

    def set_paused(self, paused: bool) -> None:
        """Выключено не человеком, а на время — например, пока работает VPN.

        Серое кольцо читалось как «выключили», и подпись под кнопкой этого не
        перебивала. Жёлтое говорит «ждёт»: так же предупреждения окрашены по
        всей программе.
        """
        if paused == self._paused:
            return
        self._paused = paused
        self._hold_anim.stop()

        # Вместе с паузой меняется и работа: зелёная дуга уже сходит или
        # наливается. Жёлтая тогда — подложка под ней: при паузе зелёное
        # открывает её целиком, при возврате закрывает и только потом уходит.
        # Смотрим на само кольцо, а не на то, идёт ли анимация: щелчок по
        # кнопке на миг запускает её сам, и пауза из серого выходила рывком.
        if paused and self._fill > 0.5:
            self.set_hold(1.0)
            return
        greening = (
            self._glow.state() == QPropertyAnimation.State.Running
            and self._glow.endValue() == 1.0
        )
        if not paused and greening:
            return

        self._hold_anim.setDuration(motion.duration(RING_FILL_MS))
        self._hold_anim.setStartValue(self._hold)
        self._hold_anim.setEndValue(1.0 if paused else 0.0)
        self._hold_anim.start()

    def set_busy(self, busy: bool) -> None:
        """Идёт ли работа. На вид кнопка не меняется — только не нажимается."""
        self._busy = busy
        self._sync_enabled()

    def _settled(self) -> None:
        self._settling = False
        self._sync_enabled()
        # Зелёная дуга закрыла жёлтую целиком — убрать её теперь незаметно.
        if not self._paused and self._hold and self._fill >= 1.0:
            self.set_hold(0.0)

    def _sync_enabled(self) -> None:
        self.setEnabled(self._available and not self._busy and not self._settling)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя задано Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        ring = QColor(COLORS["border_strong"])
        warning = QColor(COLORS["warning"])
        resting = _blend(QColor(COLORS["text_dim"]), warning, self._hold)
        glyph = _blend(resting, QColor(COLORS["text"]), self._fill)

        if self.underMouse() and self.isEnabled():
            # На светлой теме осветлять нечего: кольцо и так светлое, и
            # подсветка просто растворялась бы в фоне.
            ring = ring.darker(125) if is_light() else ring.lighter(125)

        inset = 5.0
        circle = QRectF(inset, inset, self.width() - inset * 2, self.height() - inset * 2)

        painter.setBrush(QColor(COLORS["surface"]))
        # Занятая кнопка просто не нажимается и приглушена. Пунктир по
        # кругу был лишним шагом в и без того заметной цепочке: серое
        # кольцо, пунктир, снова серое, и только потом заполнение.
        painter.setPen(QPen(ring, 2.5))
        painter.drawEllipse(circle)

        # Кольцо не перекрашивается, а обводится: цветная дуга идёт от
        # двенадцати часов по часовой стрелке и доходит до полного круга.
        # Смена цвета на тёмном фоне почти не читается — а растущая дуга
        # видна сразу и объясняет, что состояние меняется прямо сейчас.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._hold > 0.0:
            # Пауза — под зелёной дугой: при смене одного на другое зелёное
            # сходит с жёлтого или наливается поверх него.
            painter.setPen(QPen(warning, 2.5, cap=Qt.PenCapStyle.RoundCap))
            if self._hold >= 1.0:
                painter.drawEllipse(circle)
            else:
                painter.drawArc(circle, 90 * 16, -round(360 * 16 * self._hold))

        if self._fill > 0.0:
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
        # Сразу, а не с очередью событий: ширина у строки уже есть, а до пересчёта новое значение
        # успевало показаться в ширину старого, и на кадре видны были первые буквы.
        self.layout().activate()

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


def view_header(title: str, subtitle: str = "", aside: QWidget | None = None) -> QWidget:
    """Шапка экрана: заголовок и поясняющая строка под ним.

    `aside` встаёт сразу за заголовком — например, значок «как это работает»: он
    про этот экран, и место ему рядом с его названием, а не среди кнопок.
    """
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(SPACE["xs"])

    heading = QLabel(title)
    heading.setObjectName("ViewTitle")
    if aside is None:
        layout.addWidget(heading)
    else:
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(SPACE["xs"])
        line.addWidget(heading)
        line.addWidget(aside, 0, Qt.AlignmentFlag.AlignVCenter)
        line.addStretch(1)
        layout.addLayout(line)

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



class ShineProgressBar(QProgressBar):
    """Полоса прогресса с бегущим бликом — как принято у загрузок.

    Блик показывает, что работа идёт, даже когда полоса подолгу стоит на месте: одна
    стратегия проверяется несколько секунд, а у загрузки бывают паузы. Это служебное
    движение, поэтому оно подчиняется общей галочке «Анимации в интерфейсе»
    (`motion.enabled`) и не крутится, пока полосы не видно.
    """

    SWEEP_MS = 1600
    BAND = 70

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._phase = 0.0
        self._sweep = QVariantAnimation(self)
        self._sweep.setStartValue(0.0)
        self._sweep.setEndValue(1.0)
        self._sweep.setDuration(self.SWEEP_MS)
        self._sweep.setLoopCount(-1)
        self._sweep.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._sweep.valueChanged.connect(self._advance)

    def _advance(self, value) -> None:
        if not motion.enabled():
            self._sweep.stop()
        self._phase = float(value)
        self.update()

    def _filled(self) -> QRectF | None:
        span = self.maximum() - self.minimum()
        if span <= 0 or self.value() <= self.minimum():
            return None
        inner = QRectF(self.contentsRect()).adjusted(1, 1, -1, -1)
        share = (self.value() - self.minimum()) / span
        return QRectF(inner.left(), inner.top(), inner.width() * share, inner.height())

    def showEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        super().showEvent(event)
        if motion.enabled():
            self._sweep.start()

    def hideEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        super().hideEvent(event)
        self._sweep.stop()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя задано Qt
        super().paintEvent(event)
        filled = self._filled()
        if filled is None or self._sweep.state() != QVariantAnimation.State.Running:
            return

        # Блик проходит всю заполненную часть и уходит за край, а не обрывается у него.
        travel = filled.width() + self.BAND
        left = filled.left() - self.BAND + travel * self._phase
        shine = QLinearGradient(left, 0, left + self.BAND, 0)
        glare = QColor(255, 255, 255, 0)
        shine.setColorAt(0.0, glare)
        glare.setAlpha(110)
        shine.setColorAt(0.5, glare)
        glare.setAlpha(0)
        shine.setColorAt(1.0, glare)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(filled)
        painter.fillRect(filled, shine)
        painter.end()


class TabStrip(QWidget):
    """Горизонтальный ряд разделов-таблеток: выбран всегда ровно один."""

    changed = pyqtSignal(str)

    def __init__(self, tabs: list[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE["sm"])
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, Chip] = {}

        for key, title in tabs:
            button = Chip(title, key)
            # Выбранная таблетка пишется жирным, а ширину Qt считает по обычному
            # начертанию — без запаса текст обрезался по краям.
            button.ensurePolished()
            bold = QFont(button.font())
            bold.setWeight(QFont.Weight.DemiBold)
            extra = QFontMetrics(bold).horizontalAdvance(title) - button.fontMetrics(
            ).horizontalAdvance(title)
            button.setMinimumWidth(button.sizeHint().width() + max(0, extra))
            button.clicked.connect(lambda _, chosen=key: self.select(chosen))
            self._group.addButton(button)
            self.buttons[key] = button
            row.addWidget(button)
        row.addStretch(1)

        if tabs:
            self.buttons[tabs[0][0]].setChecked(True)

    def current(self) -> str:
        return next((key for key, button in self.buttons.items() if button.isChecked()), "")

    def select(self, key: str) -> None:
        if key not in self.buttons:
            return
        self.buttons[key].setChecked(True)
        self.changed.emit(key)


class IconButton(QAbstractButton):
    """Кнопка-значок без рамки: значок из `assets/icons`, цвет — от темы.

    Для мелких служебных действий вроде пояснения к экрану: текстовый «?» в
    таблетке выглядел заплаткой.
    """

    SIZE = 30
    ICON = 20

    def __init__(
        self, icon: str, tooltip: str, size: int = SIZE, icon_size: int = ICON,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._icon = icon
        self.SIZE, self.ICON = size, icon_size
        self.setToolTip(tooltip)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя задано Qt
        from app.ui.frameless import svg_renderer

        colour = COLORS["text"] if self.underMouse() and self.isEnabled() else COLORS["text_dim"]
        offset = (self.SIZE - self.ICON) / 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        svg_renderer(self._icon, colour).render(
            painter, QRectF(offset, offset, self.ICON, self.ICON)
        )
        painter.end()


class IconChip(QPushButton):
    """Таблетка со значком вместо текста — встаёт в ряд к обычным `Chip`.

    Знак «+» текстом набирался мелким шрифтом таблеток, и его горизонтальная черта
    почти пропадала. Значок рисуется векторно и толще, цветом темы.
    """

    ICON = 14

    def __init__(self, icon: str, tooltip: str, parent: QWidget | None = None):
        super().__init__("", parent)
        self._icon = icon
        self.setObjectName("Chip")
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.ensurePolished()
        height = max(self.sizeHint().height(), 26)
        self.setFixedSize(height + 6, height)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя задано Qt
        from app.ui.frameless import svg_renderer

        super().paintEvent(event)
        if not self.isEnabled():
            colour = COLORS["text_muted"]
        elif self.underMouse():
            colour = COLORS["text"]
        else:
            colour = COLORS["text_dim"]
        left = (self.width() - self.ICON) / 2
        top = (self.height() - self.ICON) / 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        svg_renderer(self._icon, colour).render(painter, QRectF(left, top, self.ICON, self.ICON))
        painter.end()
