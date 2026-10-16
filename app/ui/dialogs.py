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

        self._buttons = QHBoxLayout()
        self._buttons.setSpacing(SPACE["sm"])
        self._buttons.addStretch(1)
        body.addLayout(self._buttons)

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
