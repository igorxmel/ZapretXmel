"""Шрифт интерфейса: встроенные подключаются, свой ищется по названию, языки видны."""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from app.core.config import Settings
from app.ui import fonts
from app.ui.theme import build_stylesheet
from app.ui.theme.tokens import FONTS

BUNDLED = {"Inter", "Manrope", "Golos Text", "Rubik", "Nunito"}


@pytest.fixture(scope="module")
def app() -> QApplication:
    made = QApplication.instance() or QApplication([])
    fonts.load_bundled()
    return made


@pytest.fixture(autouse=True)
def restore():
    yield
    fonts.apply("")


def test_system_font_by_default() -> None:
    assert Settings().ui_font == ""


def test_bundled_fonts_load_and_speak_both_languages(app) -> None:
    """Встроенные выбирались ради русского интерфейса — без кириллицы им тут не место."""
    assert set(fonts.bundled()) >= BUNDLED
    for family in BUNDLED:
        assert fonts.support(family).complete, family


def test_name_is_found_regardless_of_case(app) -> None:
    assert fonts.find("golos text") == "Golos Text"
    assert fonts.find("  INTER ") == "Inter"
    assert fonts.find("") == ""


def test_missing_font_is_reported_not_applied(app) -> None:
    missing = fonts.support("Шрифт, которого нет")
    assert not missing.found
    assert "не найден" in missing.describe()

    assert fonts.apply("Шрифт, которого нет") == fonts.SYSTEM
    assert "Шрифт, которого нет" not in FONTS["ui"]


def test_chosen_font_reaches_the_stylesheet(app) -> None:
    fonts.apply("Manrope")
    assert '"Manrope"' in build_stylesheet()

    fonts.apply("")
    assert '"Manrope"' not in build_stylesheet()


def test_partial_support_is_explained() -> None:
    latin_only = fonts.Support("Something", True, cyrillic=False, latin=True)
    assert "Только латиница" in latin_only.describe()
    assert latin_only.usable and not latin_only.complete


def test_symbol_font_is_refused(monkeypatch) -> None:
    """Wingdings рисует вместо латиницы значки — интерфейс стал бы нечитаемым."""
    symbols = fonts.Support("Wingdings", True, cyrillic=False, latin=False)
    monkeypatch.setattr(fonts, "support", lambda name: symbols)

    assert not symbols.usable
    assert "значков" in symbols.describe()
    assert fonts.apply("Wingdings") == fonts.SYSTEM
    assert "Wingdings" not in FONTS["ui"]


def test_settings_offer_bundled_and_custom(app, monkeypatch) -> None:
    from app.ui.controller import Controller
    from app.ui.views import settings as screen

    monkeypatch.setattr(Settings, "save", lambda self: None)
    monkeypatch.setattr(screen, "use_theme", lambda name: name)
    view = screen.SettingsView(Controller(Settings()))
    view.reload()

    titles = [view._font.itemText(i) for i in range(view._font.count())]
    assert titles[0].startswith("Как в Windows")
    assert set(titles) >= BUNDLED
    assert view._font.itemData(view._font.count() - 1) == screen.CUSTOM_FONT

    view._font.setCurrentIndex(view._font.findData("Rubik"))
    assert view.controller.settings.ui_font == "Rubik"
    assert '"Rubik"' in FONTS["ui"]

    view._font.setCurrentIndex(view._font.count() - 1)
    assert not view._font_custom.isHidden()
    view._font_name.setText("нет такого шрифта")
    view._apply_custom_font()
    assert view.controller.settings.ui_font == "Rubik"
    assert "не найден" in view._font_note.text()
