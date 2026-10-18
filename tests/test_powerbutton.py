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


def test_busy_without_a_change_plays_nothing(app: QApplication) -> None:
    """Чужая работа не должна проигрывать анимацию на этой кнопке.

    Кнопка прокси помечала занятой кнопку обхода: та гасла пунктиром, а
    потом проигрывала выключение — хотя обход никто не трогал.
    """
    button = PowerButton()

    button.set_busy(True)
    button.set_busy(False)

    assert button.get_fill() == 0.0, "кольцо осталось там же, где было"


def test_ring_goes_straight_to_the_new_state(app: QApplication) -> None:
    """Кольцо идёт к цели и не делает лишних остановок по дороге.

    Промежуточные состояния оборачивались морганием: кольцо гасло в серое,
    заливалось целиком и только потом сливалось обратно — при том, что
    человек нажал «выключить».
    """
    button = PowerButton()
    button.setChecked(True)
    button.set_fill(1.0)

    button.setChecked(False)

    assert button.get_fill() == 1.0, "переход начинается оттуда, где кольцо сейчас"


def test_button_locks_while_the_ring_moves(app: QApplication) -> None:
    """Каждое нажатие — работа со службой, накопленные расходятся с видимым."""
    button = PowerButton()

    button.setChecked(True)

    assert not button.isEnabled()
