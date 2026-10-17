"""Тесты главной кнопки.

Нужен QApplication, поэтому тест живёт отдельно: остальные обходятся без
графики. Проверяется ровно то, на чём кнопка ломалась.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from app.ui.widgets import PowerButton


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_repeated_switching_does_not_crash(app: QApplication) -> None:
    """Вторая смена состояния роняла программу.

    Обработчик конца анимации подключался при каждом переключении с флагом
    «только один раз», а PyQt на повторное подключение бросает TypeError.
    Первое нажатие проходило, второе — падало с окном «сбой».
    """
    button = PowerButton()

    for step in range(5):
        button.setChecked(step % 2 == 0)
        button.set_busy(True)
        button.set_busy(False)


def test_button_locks_until_the_switch_finishes(app: QApplication) -> None:
    """Нажатия копились и выполнялись одно за другим.

    Каждое — это включение или выключение обхода, то есть работа со
    службой; состояние расходилось с тем, что видно на экране.
    """
    button = PowerButton()
    button.setChecked(True)
    button.set_busy(True)

    assert not button.isEnabled()

    button.set_busy(False)

    assert not button.isEnabled(), "пока кольцо не дошло, нажимать нельзя"
