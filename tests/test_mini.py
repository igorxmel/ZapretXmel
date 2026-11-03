"""Мини-окно и справка.

Нужен QApplication.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QByteArray
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

from app.core import guide, paths
from app.core.config import Settings
from app.ui.controller import Controller, Status
from app.ui.views.help import HelpWindow
from app.ui.views.mini import MiniView

SECTIONS = (("dashboard", "Обзор"), ("autopick", "Подбор"), ("updates", "Обновления"))
ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def mini(app: QApplication) -> MiniView:
    return MiniView(Controller(Settings()), SECTIONS)


def test_menu_lists_everything_except_the_overview(mini: MiniView) -> None:
    assert [action.text() for action in mini._menu.actions()] == ["Подбор", "Обновления"]


def test_menu_opens_the_section(mini: MiniView) -> None:
    opened: list[str] = []
    mini.section_requested.connect(opened.append)

    mini._menu.actions()[1].trigger()

    assert opened == ["updates"]


def test_update_notice_follows_the_reminder(mini: MiniView) -> None:
    """Полосы об обновлении здесь нет, а узнать о нём всё равно надо."""
    assert mini._update.isHidden()

    mini.set_update_available(True)
    assert not mini._update.isHidden()

    mini.set_update_available(False)
    assert mini._update.isHidden()


def test_status_reaches_all_controls(mini: MiniView) -> None:
    mini.apply_status(
        Status(core_present=True, winws_count=1, active_strategy="general", active_vpn="Meta")
    )

    assert mini.power.bypass.button.isChecked()
    assert not mini.notices.isHidden()


def test_menu_button_has_a_drawn_icon_instead_of_a_symbol(mini: MiniView) -> None:
    mini.reload()

    assert mini.menu_button.text() == "Все разделы"
    assert not mini.menu_button.icon().isNull()


def test_compact_choice_survives_restart() -> None:
    assert Settings.from_dict({"compact_mode": True}).compact_mode is True
    assert Settings.from_dict({}).compact_mode is False


# --- справка ----------------------------------------------------------------


def test_help_has_steps_and_questions() -> None:
    text = guide.help_markdown()

    assert "С чего начать" in text
    assert "Что такое ZapretXmel?" in text


def test_help_drops_notes_for_developers() -> None:
    text = guide.help_markdown()

    assert "tests/test_faq.py" not in text
    assert "<!--" not in text


def test_help_works_without_the_questions_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paths, "assets_dir", lambda: tmp_path / "нет")
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path / "тоже нет")

    assert guide.help_markdown() == guide.STEPS


def test_packed_questions_win_over_the_source_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / guide.FAQ_FILENAME).write_text("# Шапка\n\n## Вопрос?\n\nОтвет", encoding="utf-8")
    monkeypatch.setattr(paths, "assets_dir", lambda: tmp_path)

    assert guide.faq_markdown() == "## Вопрос?\n\nОтвет"


def test_questions_are_packed_into_the_build() -> None:
    """Без этого в собранной версии справка потеряла бы вопросы, а тесты бы молчали."""
    source = (ROOT / "tools" / "build_release.py").read_text(encoding="utf-8")

    assert "FAQ.md" in source


@pytest.mark.parametrize("name", ["Подбор стратегии", "Применить лучшую", "Применить и включить"])
def test_steps_name_real_buttons(name: str) -> None:
    """Шаги ссылаются на кнопки словами, и при переименовании врали бы молча."""
    assert name in guide.STEPS
    sources = [*(ROOT / "app" / "ui").rglob("*.py")]
    used = (path.read_text(encoding="utf-8") for path in sources)
    assert any(f'"{name}"' in text for text in used)


def test_help_window_opens(app: QApplication) -> None:
    assert "С чего начать" in HelpWindow().text.toPlainText()


ICONS = ["window-help", "window-shrink", "window-expand", "window-sections"]


@pytest.mark.parametrize("icon", ICONS)
def test_title_icons_are_valid_and_follow_the_theme(icon: str) -> None:
    """Цвет подставляется из темы, поэтому в файле он должен быть не задан жёстко."""
    text = (ROOT / "assets" / "icons" / f"{icon}.svg").read_text(encoding="utf-8")

    assert "currentColor" in text
    assert QSvgRenderer(QByteArray(text.replace("currentColor", "#fff").encode())).isValid()
