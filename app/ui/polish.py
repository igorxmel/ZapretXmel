"""«Объёмное оформление» — слой поверх обычного вида, который выключается одной галочкой.

Что в нём:
- карточки с объёмом: светлая кромка сверху в тёмной теме, тень снизу в светлой;
- раздел при переходе проявляется, а не подменяется в тот же кадр;
- окна справки и диалоги появляются плавно;
- уведомления всплывают поверх окна, а не строкой внизу: строка то появлялась, то
  исчезала и каждый раз сдвигала всю страницу на свою высоту.

Всё это — отдельно от `motion`: тот отвечает за служебное движение и выключается
на слабых машинах, а здесь вкус. Выключили «Анимации» — объём остаётся, только без
плавности. Выключили это — программа выглядит так, как до 0.4.11.
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from app.ui import motion
from app.ui.theme.tokens import BRAND, COLORS, RADIUS, SPACE, is_light

_enabled = True

PAGE_MS = 180
WINDOW_MS = 160
TOAST_IN_MS = 180
TOAST_OUT_MS = 260


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)


def enabled() -> bool:
    return _enabled


def _animated() -> bool:
    return _enabled and motion.enabled()


def fade_in(widget: QWidget, ms: int = PAGE_MS) -> None:
    """Проявляет виджет. Эффект снимается сразу после: с ним Qt рисует через буфер,
    а постоянно так рисовать таблицы и длинные списки — заметно медленнее."""
    if not _animated() or not widget.isVisible():
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(ms)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


def fade_window(window: QWidget, ms: int = WINDOW_MS) -> None:
    """Окно верхнего уровня проявляется через собственную прозрачность."""
    if not _animated():
        return
    window.setWindowOpacity(0.0)
    animation = QPropertyAnimation(window, b"windowOpacity", window)
    animation.setDuration(ms)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


def card_rules() -> str:
    """Добавка к таблице стилей: кромка, которая отделяет карточку от фона.

    Настоящие тени через QGraphicsDropShadowEffect здесь не годятся: виджет с таким
    эффектом рисуется картинкой, текст теряет чёткость ClearType, а прокрутка длинных
    экранов начинает подтормаживать. Кромка даёт тот же объём бесплатно.
    """
    if not _enabled:
        return ""
    c = COLORS
    # Объём даёт свет, а не толщина рамки: верх карточки чуть светлее, низ темнее, как
    # у поверхности под лампой. Кромка сверху — блик на ребре.
    if is_light():
        top, bottom = "#ffffff", _mix(c["surface"], c["bg"], 0.6)
        edge = (
            f"border: 1px solid {c['border']};"
            f"border-bottom: 1px solid {_mix(c['border'], c['border_strong'], 0.6)};"
        )
    else:
        top, bottom = _mix(c["surface"], "#ffffff", 0.06), _mix(c["surface"], c["bg"], 0.35)
        edge = (
            f"border: 1px solid {c['border']};"
            f"border-top: 1px solid {_mix(c['border'], '#ffffff', 0.12)};"
        )
    fill = (
        "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        f"stop:0 {top}, stop:1 {bottom});"
    )
    return f"\nQFrame#Card {{ {fill} {edge} }}\n"


def _mix(first: str, second: str, share: float) -> str:
    """Цвет между двумя: share = 0 — первый, 1 — второй."""
    a, b = QColor(first), QColor(second)
    blend = QColor(
        round(a.red() + (b.red() - a.red()) * share),
        round(a.green() + (b.green() - a.green()) * share),
        round(a.blue() + (b.blue() - a.blue()) * share),
    )
    return blend.name()


class Toast(QWidget):
    """Всплывающее уведомление поверх окна: точка цвета и текст в капсуле."""

    MAX_WIDTH = 520

    def __init__(self, host: QWidget):
        super().__init__(host)
        self._host = host
        self._colour = QColor(COLORS["text_dim"])
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE["xl"] + SPACE["sm"], SPACE["md"], SPACE["lg"], SPACE["md"])
        self._label = QLabel("")
        self._label.setWordWrap(True)
        row.addWidget(self._label)

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.finished.connect(self._faded)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

        host.installEventFilter(self)
        self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 — имя Qt
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self._place()
        return False

    def show_message(self, text: str, colour: str, ms: int) -> None:
        # Обычное сообщение — фирменной точкой: серая на сером фоне читалась как «выключено».
        self._colour = QColor(BRAND["orange"] if colour == COLORS["text_dim"] else colour)
        self._label.setText(text)
        self._label.setStyleSheet(f"color: {COLORS['text']};")
        self._place()
        self.raise_()
        self._fade.stop()
        if not self.isVisible():
            self._opacity.setOpacity(0.0)
            self.show()
        self._fade.setDuration(motion.duration(TOAST_IN_MS))
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(ms)

    def dismiss(self) -> None:
        self._fade.stop()
        self._fade.setDuration(motion.duration(TOAST_OUT_MS))
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def text(self) -> str:
        return self._label.text() if self.isVisible() else ""

    def _faded(self) -> None:
        if self._opacity.opacity() <= 0.01:
            self.hide()

    def _place(self) -> None:
        width = min(self.MAX_WIDTH, max(200, self._host.width() - SPACE["xl"] * 2))
        self.setFixedWidth(width)
        self.adjustSize()
        x = (self._host.width() - width) // 2
        y = self._host.height() - self.height() - SPACE["xl"]
        self.move(x, max(0, y))

    def paintEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(box, RADIUS["lg"], RADIUS["lg"])
        painter.fillPath(path, QColor(COLORS["elevated"]))
        painter.setPen(QColor(COLORS["border_strong"]))
        painter.drawPath(path)
        dot = 8
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._colour)
        painter.drawEllipse(
            QRectF(SPACE["lg"], (self.height() - dot) / 2, dot, dot)
        )
        painter.end()
