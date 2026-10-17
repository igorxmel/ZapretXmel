"""Вопросы и предупреждения в оформлении программы.

`QMessageBox` рисует сама Windows: таблица стилей до него не доходит, и
посреди тёмного окна открывается светлый системный прямоугольник с чужими
шрифтами и кнопками «ОК». Особенно заметно это на удалении — там вопрос
серьёзный, а выглядит он так, будто его задаёт другая программа.

Поэтому окно своё: та же рамка и тот же заголовок, что у окна знакомства,
и те же кнопки, что по всей программе. Растягивать его нечего, так что
заголовок берётся в компактном виде — только закрытие.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.frameless import TitleBar
from app.ui.theme.tokens import COLORS, SPACE

DIALOG_WIDTH = 460


class Dialog(QDialog):
    """Модальное окно с вопросом и своими кнопками.

    Кнопки добавляются по одной: подписи у них должны называть действие
    («Удалить», «Перенести»), а не отвечать «да» и «нет» — из «да» не
    видно, на что соглашаешься.
    """

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        text: str,
        details: str = "",
        tone: str = "",
    ):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(DIALOG_WIDTH)

        self._answer: str = ""

        shell = QVBoxLayout(self)
        shell.setContentsMargins(1, 1, 1, 1)
        shell.setSpacing(0)

        frame = QFrame()
        frame.setObjectName("WindowFrame")
        shell.addWidget(frame)

        inner = QVBoxLayout(frame)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        inner.addWidget(TitleBar(self, title, compact=True))

        body = QVBoxLayout()
        body.setContentsMargins(
            SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"]
        )
        body.setSpacing(SPACE["md"])
        inner.addLayout(body)

        headline = QLabel(text)
        headline.setObjectName("DialogText")
        headline.setWordWrap(True)
        if tone:
            headline.setStyleSheet(f"color: {COLORS[tone]};")
        body.addWidget(headline)

        if details:
            explanation = QLabel(details)
            explanation.setObjectName("Muted")
            explanation.setWordWrap(True)
            body.addWidget(explanation)

        # Место для содержимого между объяснением и кнопками: поле ввода,
        # список, что угодно.
        self._extra = QVBoxLayout()
        self._extra.setSpacing(SPACE["sm"])
        body.addLayout(self._extra)

        self._buttons = QHBoxLayout()
        self._buttons.setSpacing(SPACE["sm"])
        self._buttons.addStretch(1)
        body.addLayout(self._buttons)

    def insert_widget(self, widget: QWidget) -> None:
        """Добавляет виджет между объяснением и кнопками."""
        self._extra.addWidget(widget)

    def insert_layout(self, layout) -> None:
        self._extra.addLayout(layout)

    def add_action(self, label: str, *, danger: bool = False, primary: bool = False) -> None:
        """Добавляет кнопку, закрывающую окно с ответом в виде её подписи."""
        button = QPushButton(label)
        if danger:
            button.setObjectName("Danger")
        elif primary:
            button.setObjectName("Primary")
        button.clicked.connect(lambda: self._answer_with(label))
        self._buttons.addWidget(button)

    def _answer_with(self, label: str) -> None:
        self._answer = label
        self.accept()

    def ask(self) -> str:
        """Показывает окно и возвращает подпись нажатой кнопки.

        Закрыли крестиком — пустая строка: это отказ, и обрабатывать его
        надо так же, как «Отмена».
        """
        self.exec()
        return self._answer


def confirm(
    parent: QWidget | None,
    title: str,
    text: str,
    details: str = "",
    *,
    action: str = "Продолжить",
    danger: bool = False,
) -> bool:
    """Спрашивает подтверждение. Кнопка согласия названа своим действием."""
    dialog = Dialog(parent, title, text, details, tone="danger" if danger else "")
    dialog.add_action("Отмена")
    dialog.add_action(action, danger=danger, primary=not danger)
    return dialog.ask() == action


def ask_text(
    parent: QWidget | None,
    title: str,
    text: str,
    details: str = "",
    *,
    value: str = "",
    placeholder: str = "",
    action: str = "Сохранить",
) -> str:
    """Спрашивает строку. Пустая строка — отказались.

    Вместо `QInputDialog`: тот рисуется системой, выходит крошечным светлым
    окошком посреди тёмного и не даёт ни объяснить, зачем спрашиваем, ни
    назвать кнопку делом.
    """
    dialog = Dialog(parent, title, text, details)

    field = QLineEdit(value)
    field.setPlaceholderText(placeholder)
    field.selectAll()
    dialog.insert_widget(field)

    dialog.add_action("Отмена")
    dialog.add_action(action, primary=True)

    # Enter в поле — то же, что нажать кнопку: иначе приходится тянуться мышью
    # после того, как имя уже набрано.
    field.returnPressed.connect(lambda: dialog._answer_with(action))
    field.setFocus()

    return field.text().strip() if dialog.ask() == action else ""


def tell(
    parent: QWidget | None,
    title: str,
    text: str,
    details: str = "",
    *,
    tone: str = "",
    button: str = "Понятно",
) -> None:
    """Сообщает что-то, на что нужно просто ответить «ладно»."""
    dialog = Dialog(parent, title, text, details, tone=tone)
    dialog.add_action(button, primary=True)
    dialog.ask()
