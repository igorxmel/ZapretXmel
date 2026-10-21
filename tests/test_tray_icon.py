"""Тесты значка в трее.

Нужен QApplication: без него Qt не умеет ни читать PNG, ни рисовать. Поэтому
тест живёт отдельно, как и у главной кнопки.

Проверяется то, на чём значок может сломаться молча: упрощённый логотип на
месте и читается, рисуются все сочетания состояния и отметки во всех размерах,
отсутствие картинки не роняет программу, а откатывает на классику.
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from app.core import paths
from app.ui import tray


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


STYLES = ("classic", "modern")
BADGES = ("", "update", "alert")
STATES = ((False, False), (True, False), (False, True), (True, True))


def test_simplified_logo_is_present_and_readable(app: QApplication) -> None:
    """Пропавшая картинка сама по себе не видна: значок молча откатится на классику
    и человек решит, что оформление просто не переключилось."""
    path = paths.tray_logo_file()
    assert path.exists(), "нет assets/tray-logo.png — запустите tools/make_tray_icons.py"

    pixmap = QPixmap(str(path))
    assert not pixmap.isNull()
    assert pixmap.width() == pixmap.height(), "логотип обязан быть квадратным"


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("badge", BADGES)
@pytest.mark.parametrize(("active", "proxy"), STATES)
def test_every_combination_draws(
    app: QApplication, style: str, badge: str, active: bool, proxy: bool
) -> None:
    icon = tray.build_icon(active, proxy, style=style, badge=badge)

    assert not icon.isNull()
    # Рисунок под каждый размер, а не один сжатый: иначе на 16 пикселях каша.
    assert len(icon.availableSizes()) == len(tray.ICON_SIZES)


def test_modern_logo_fills_the_frame_along_its_longer_side(app: QApplication) -> None:
    """Ради этого значок и делался крупнее: пустое поле в трее — потерянные пиксели.

    Замок выше, чем шире, поэтому по меньшей стороне поле остаётся — растягивать
    рисунок до квадрата значило бы его исказить. Проверяется сам ресурс: кружки
    рисуются поверх и размыли бы границу.
    """
    image = QPixmap(str(paths.tray_logo_file())).toImage()
    side = image.width()

    rows = [y for y in range(side) if any(
        image.pixelColor(x, y).alpha() > 8 for x in range(0, side, 2))]
    columns = [x for x in range(side) if any(
        image.pixelColor(x, y).alpha() > 8 for y in range(0, side, 2))]

    assert rows[0] <= 1 and rows[-1] >= side - 2, "по высоте рисунок обязан занимать весь кадр"
    assert (columns[-1] - columns[0] + 1) >= 0.8 * side, "по ширине он не должен быть мелким"


def test_modern_falls_back_to_classic_without_the_picture(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Картинки нет — рисуем классику, а не падаем и не показываем пустоту.

    Так бывает у того, кто обновился со старой версии мимо сборки, или если
    картинку вырезал антивирус. Значок в трее — не та вещь, из-за которой
    стоит ронять программу.
    """
    monkeypatch.setattr(paths, "tray_logo_file", lambda: paths.assets_dir() / "нет.png")

    icon = tray.build_icon(active=True, style="modern")

    assert not icon.isNull()


def test_badge_changes_the_picture(app: QApplication) -> None:
    """Отметка должна быть видна: иначе она есть в коде и нет на экране."""
    logo = tray._modern_logo()
    plain = tray._paint(64, logo, True, False, True, "").toImage()
    for badge in ("update", "alert"):
        marked = tray._paint(64, logo, True, False, True, badge).toImage()
        assert marked != plain, badge


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
