"""Оформление по частям: вид карточек, плавность и уведомления включаются отдельно."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.ui import polish
from app.ui.theme import build_stylesheet


@pytest.fixture(autouse=True)
def restore():
    yield
    polish.configure(polish.DEFAULT_CARDS, True, True)


def test_defaults() -> None:
    settings = Settings()
    assert settings.card_style == "raised"
    assert settings.smooth_pages and settings.floating_toasts
    assert Settings.from_dict({}).card_style == "raised"


def test_old_switch_off_means_everything_off() -> None:
    """Сняли прежнюю общую галочку — хотели прежний вид целиком."""
    settings = Settings.from_dict({"polish": False})

    assert settings.card_style == "flat"
    assert not settings.smooth_pages and not settings.floating_toasts


def test_old_switch_on_keeps_the_gradient() -> None:
    """Кто жил с градиентом, тот его и видит, пока сам не сменит."""
    assert Settings.from_dict({"polish": True}).card_style == "gradient"
    assert Settings.from_dict({"polish": True, "card_style": "outline"}).card_style == "outline"


def test_flat_cards_add_nothing() -> None:
    polish.configure(cards="raised")
    raised = build_stylesheet()
    polish.configure(cards="flat")
    flat = build_stylesheet()

    assert polish.card_rules() == ""
    assert flat != raised
    assert raised.startswith(flat.rstrip()[:200])


@pytest.mark.parametrize("style", ["outline", "raised", "gradient"])
def test_each_style_styles_the_card(style: str) -> None:
    polish.configure(cards=style)
    assert "QFrame#Card" in polish.card_rules()


def test_only_the_gradient_has_a_gradient() -> None:
    """Серые подписи у светлого верха градиента сливались — остальные виды ровные."""
    polish.configure(cards="gradient")
    assert "qlineargradient" in polish.card_rules()
    for style in ("outline", "raised"):
        polish.configure(cards=style)
        assert "qlineargradient" not in polish.card_rules()


def test_unknown_style_falls_back() -> None:
    polish.configure(cards="neon")
    assert polish.card_style() == polish.DEFAULT_CARDS


def test_parts_switch_separately() -> None:
    polish.configure(fades=False)
    assert not polish._animated()
    assert polish.toasts_enabled()
    assert polish.card_style() == polish.DEFAULT_CARDS


def test_no_motion_means_no_fade(monkeypatch) -> None:
    """Галочка «Анимации» главнее: на слабой машине ничего не проявляется."""
    from app.ui import motion

    monkeypatch.setattr(motion, "_enabled", False)
    assert not polish._animated()


def test_links_are_orange(qapp=None) -> None:
    """Ссылка в надписи брала цвет из палитры Qt и выходила тёмно-розовой."""
    from PyQt6.QtWidgets import QApplication

    from app.ui.theme.live import apply_palette
    from app.ui.theme.tokens import BRAND

    app = QApplication.instance() or QApplication([])
    apply_palette(app)

    assert app.palette().link().color().name().lower() == BRAND["orange"].lower()
