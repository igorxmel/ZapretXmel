"""«Объёмное оформление» выключается одной галочкой и возвращает прежний вид."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.ui import polish
from app.ui.theme import build_stylesheet


@pytest.fixture(autouse=True)
def restore():
    yield
    polish.set_enabled(True)


def test_on_by_default() -> None:
    assert Settings().polish is True
    assert Settings.from_dict({}).polish is True


def test_switching_off_restores_the_flat_cards() -> None:
    polish.set_enabled(True)
    with_polish = build_stylesheet()
    polish.set_enabled(False)
    flat = build_stylesheet()

    assert polish.card_rules() == ""
    assert flat != with_polish
    assert with_polish.startswith(flat.rstrip()[:200])


def test_no_motion_means_no_fade(monkeypatch) -> None:
    """Галочка «Анимации» главнее: на слабой машине ничего не проявляется."""
    from app.ui import motion

    monkeypatch.setattr(motion, "_enabled", False)
    assert not polish._animated()


def test_cards_get_light_not_just_a_thicker_border() -> None:
    """Кромка в пару пикселей читалась как обводка потолще — объём даёт градиент."""
    polish.set_enabled(True)

    assert "qlineargradient" in polish.card_rules()


def test_links_are_orange(qapp=None) -> None:
    """Ссылка в надписи брала цвет из палитры Qt и выходила тёмно-розовой."""
    from PyQt6.QtWidgets import QApplication

    from app.ui.theme.live import apply_palette
    from app.ui.theme.tokens import BRAND

    app = QApplication.instance() or QApplication([])
    apply_palette(app)

    assert app.palette().link().color().name().lower() == BRAND["orange"].lower()
