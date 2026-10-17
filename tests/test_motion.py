"""Тесты выключателя анимаций.

Анимации здесь служебные: они подсказывают, что состояние сменилось. Но на
слабой машине и через удалённый рабочий стол любое движение лишнее, поэтому
его можно убрать целиком.
"""

from __future__ import annotations

import pytest

from app.ui import motion


@pytest.fixture(autouse=True)
def restore() -> None:
    """Выключатель один на всё приложение — вернём его на место после теста."""
    was = motion.enabled()
    yield
    motion.set_enabled(was)


def test_animations_are_on_by_default() -> None:
    assert motion.enabled()


def test_disabled_animations_take_no_time() -> None:
    """Ноль вместо ветвления в каждом виджете: Qt доводит значение за кадр."""
    motion.set_enabled(False)

    assert motion.duration(260) == 0


def test_enabled_animations_keep_their_duration() -> None:
    motion.set_enabled(True)

    assert motion.duration(260) == 260
