"""Окно «Как пользоваться»: шаги с номерами и раскрывающиеся частые вопросы.

Раньше здесь был один длинный текст из Markdown. Шаги в нём сливались с вопросами, а
нужный вопрос приходилось искать прокруткой. Теперь две вкладки: по шагам видно,
сколько их и на каком ты, а вопросы раскрываются по одному.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.core import guide
from app.ui.frameless import FramelessWindow, svg_renderer
from app.ui.theme.tokens import BRAND, COLORS, SPACE
from app.ui.widgets import TabStrip, set_markdown


class StepNumber(QWidget):
    """Оранжевый кружок с номером шага."""

    SIZE = 28

    def __init__(self, number: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._number = number
        self.setFixedSize(self.SIZE, self.SIZE)

    def paintEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BRAND["orange"]))
        painter.drawEllipse(QRectF(0, 0, self.SIZE, self.SIZE))
        font = QFont(self.font())
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self._number))
        painter.end()


class StepRow(QWidget):
    """Шаг: номер слева, заголовок и пояснение справа. Между шагами — линия-связка."""

    def __init__(self, number: int, title: str, text: str, last: bool, parent=None):
        super().__init__(parent)
        self._last = last
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0 if last else SPACE["lg"])
        row.setSpacing(SPACE["lg"])
        row.addWidget(StepNumber(number), 0, Qt.AlignmentFlag.AlignTop)

        words = QVBoxLayout()
        words.setSpacing(SPACE["xs"])
        heading = QLabel(title)
        heading.setObjectName("HelpStepTitle")
        words.addWidget(heading)
        body = QLabel(text)
        body.setObjectName("Dim")
        body.setWordWrap(True)
        words.addWidget(body)
        row.addLayout(words, 1)

    def paintEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        if self._last:
            return
        painter = QPainter(self)
        painter.setPen(QColor(COLORS["border_strong"]))
        x = StepNumber.SIZE / 2
        painter.drawLine(QRectF(x, StepNumber.SIZE + 4, 0, 0).topLeft(),
                         QRectF(x, self.height() - 4, 0, 0).topLeft())
        painter.end()


class Tip(QFrame):
    """Совет сбоку от шагов: Telegram, мини-окно."""

    def __init__(self, title: str, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("HelpTip")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        layout.setSpacing(SPACE["xs"])
        heading = QLabel(title)
        heading.setObjectName("HelpStepTitle")
        layout.addWidget(heading)
        body = QLabel(text)
        body.setObjectName("Dim")
        body.setWordWrap(True)
        layout.addWidget(body)


class AnswerText(QTextBrowser):
    """Ответ в разметке, ровно по высоте текста: прокрутка у страницы, а не у ответа."""

    def __init__(self, markdown: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("HelpAnswer")
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        set_markdown(self, markdown)
        self.document().setDocumentMargin(0)

    def _fit(self) -> None:
        self.document().setTextWidth(self.viewport().width())
        # Поля и рамка из общей таблицы стилей: без них последняя строка обрезалась.
        chrome = self.height() - self.viewport().height()
        self.setFixedHeight(int(self.document().size().height()) + chrome + 2)

    def resizeEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        super().showEvent(event)
        self._fit()


class QuestionButton(QPushButton):
    """Заголовок вопроса со стрелкой справа: вниз — свёрнут, вверх — раскрыт."""

    ICON = 14

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("HelpQuestion")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802 — имя задано Qt
        hint = super().sizeHint()
        return QSize(hint.width() + self.ICON + SPACE["md"], hint.height())

    def paintEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left = self.width() - self.ICON - SPACE["lg"]
        top = (self.height() - self.ICON) / 2
        if self.isChecked():
            # Та же стрелка, перевёрнутая: второй файл ради неё не нужен.
            painter.translate(left + self.ICON / 2, top + self.ICON / 2)
            painter.rotate(180)
            painter.translate(-(left + self.ICON / 2), -(top + self.ICON / 2))
        colour = COLORS["text"] if self.isChecked() or self.underMouse() else COLORS["text_dim"]
        svg_renderer("window-chevron", colour).render(
            painter, QRectF(left, top, self.ICON, self.ICON)
        )
        painter.end()


class FaqItem(QFrame):
    """Вопрос, который раскрывается по щелчку."""

    def __init__(self, question: str, answer: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("HelpItem")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.button = QuestionButton(question)
        layout.addWidget(self.button)

        self.answer = AnswerText(answer)
        holder = QWidget()
        inner = QVBoxLayout(holder)
        inner.setContentsMargins(SPACE["lg"], 0, SPACE["lg"], SPACE["lg"])
        inner.addWidget(self.answer)
        self._holder = holder
        holder.hide()
        layout.addWidget(holder)

        self.button.toggled.connect(self.set_open)

    def set_open(self, opened: bool) -> None:
        self.button.setChecked(opened)
        self._holder.setVisible(opened)
        self.setProperty("open", opened)
        self.style().unpolish(self)
        self.style().polish(self)


def _scroll_page(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    return scroll


class HelpWindow(FramelessWindow):
    """Справка. Вопросы берутся из FAQ.md, поэтому второй текст поддерживать не нужно."""

    def __init__(self):
        super().__init__("Как пользоваться", compact=True, resizable=True, caption="Справка")
        # На ноутбуке с увеличением экрана в логических точках совсем немного.
        screen = QApplication.primaryScreen()
        room = screen.availableGeometry().height() if screen else 720
        self.setMinimumSize(560, min(480, int(room * 0.9)))
        self.resize(700, min(720, int(room * 0.94)))

        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["lg"])
        layout.setSpacing(SPACE["md"])

        title = QLabel("Как пользоваться")
        title.setObjectName("ViewTitle")
        layout.addWidget(title)
        subtitle = QLabel("Пять шагов до работающего обхода и ответы на частые вопросы.")
        subtitle.setObjectName("ViewSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.faq = [FaqItem(question, answer) for question, answer in guide.faq_items()]
        tabs = [("start", "С чего начать")]
        if self.faq:
            tabs.append(("faq", f"Частые вопросы · {len(self.faq)}"))
        self.tabs = TabStrip(tabs)
        layout.addWidget(self.tabs)

        self.pages = QStackedWidget()
        self.pages.addWidget(_scroll_page(self._build_steps()))
        if self.faq:
            self.pages.addWidget(_scroll_page(self._build_faq()))
        layout.addWidget(self.pages, 1)
        self.tabs.changed.connect(
            lambda key: self.pages.setCurrentIndex(0 if key == "start" else 1)
        )

        footer = QHBoxLayout()
        ask = QPushButton("Не нашли ответа? Спросите на GitHub")
        ask.setObjectName("Link")
        ask.setCursor(Qt.CursorShape.PointingHandCursor)
        ask.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(guide.ASK_URL)))
        footer.addWidget(ask)
        footer.addStretch(1)
        close = QPushButton("Понятно")
        close.setObjectName("Primary")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)

    def _build_steps(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SPACE["xs"], SPACE["md"], SPACE["md"], SPACE["md"])
        layout.setSpacing(0)
        count = len(guide.STEP_ITEMS)
        self.steps = [
            StepRow(number, title, text, last=number == count)
            for number, (title, text) in enumerate(guide.STEP_ITEMS, 1)
        ]
        for step in self.steps:
            layout.addWidget(step)

        layout.addSpacing(SPACE["xl"])
        tips = QHBoxLayout()
        tips.setSpacing(SPACE["md"])
        for title, text in guide.TIPS:
            tips.addWidget(Tip(title, text), 1)
        layout.addLayout(tips)
        layout.addStretch(1)
        return page

    def _build_faq(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, SPACE["md"], SPACE["md"], SPACE["md"])
        layout.setSpacing(SPACE["sm"])
        for item in self.faq:
            layout.addWidget(item)
        layout.addStretch(1)
        # Первый вопрос открыт: сразу видно, что они раскрываются.
        self.faq[0].set_open(True)
        return page

    def show_questions(self) -> None:
        self.tabs.select("faq")
