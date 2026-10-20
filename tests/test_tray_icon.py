"""Тесты значка в трее.

Нужен QApplication: без него Qt не умеет ни читать PNG, ни рисовать. Поэтому
тест живёт отдельно, как и у главной кнопки.

Проверяется то, на чём значок может сломаться молча: набор картинок на месте
и полон, отметка выбирается по правилу «тревога важнее обновления», а
отсутствие набора не роняет программу, а откатывает на классику.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from app.core import paths
from app.ui import tray


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


STATES = ("bypass", "both", "telegram", "off")
BADGES = ("", "-update", "-alert")


def test_every_state_has_a_picture(app: QApplication) -> None:
    """Двенадцать клеток листа — двенадцать файлов.

    Пропущенный файл сам по себе не виден: значок молча откатится на
    классику, и человек решит, что оформление просто не переключилось.
    """
    missing = [
        f"{state}{badge}.png"
        for state in STATES
        for badge in BADGES
        if not paths.tray_icon_file(f"{state}{badge}").exists()
    ]
    assert not missing, f"нет значков: {', '.join(missing)}"


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("badge", BADGES)
def test_pictures_are_readable(app: QApplication, state: str, badge: str) -> None:
    """Файл есть — но Qt должен его ещё и прочитать."""
    icon = tray.build_icon(
        active=state in ("bypass", "both"),
        proxy=state in ("telegram", "both"),
        style="modern",
        badge=badge.lstrip("-"),
    )
    assert not icon.isNull()


def test_modern_falls_back_to_classic_without_pictures(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Набора нет — рисуем классику, а не падаем и не показываем пустоту.

    Так бывает у того, кто обновился со старой версии мимо сборки, или если
    картинки вырезал антивирус. Значок в трее — не та вещь, из-за которой
    стоит ронять программу.
    """
    monkeypatch.setattr(paths, "tray_icon_file", lambda name: paths.assets_dir() / "нет.png")

    icon = tray.build_icon(active=True, style="modern")

    assert not icon.isNull()


def test_alert_outranks_update() -> None:
    """Обход, который не работает, важнее новой версии.

    Два признака держатся отдельно нарочно: с одним полем «какая отметка»
    прошедшая проверка сторожа не могла снять тревогу, не затерев заодно
    найденное обновление.
    """
    assert tray.choose_badge(has_alert=True, has_update=True) == "alert"
    assert tray.choose_badge(has_alert=True, has_update=False) == "alert"
    assert tray.choose_badge(has_alert=False, has_update=True) == "update"
    assert tray.choose_badge(has_alert=False, has_update=False) == ""
