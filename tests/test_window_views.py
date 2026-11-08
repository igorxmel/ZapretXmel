"""Смена вида главного окна. Нужен QApplication.

Создаётся настоящее окно: важно именно то, как его виды влияют друг на друга.
"""

from __future__ import annotations

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import __version__
from app.core import updates
from app.core.config import Settings
from app.ui.shell import MainWindow
from app.ui.theme.tokens import SIZE


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> MainWindow:
    monkeypatch.setattr(Settings, "save", lambda _self: None)
    shown = MainWindow(
        Settings(
            first_run_done=True,
            last_seen_version=__version__,
            ignored_updates=list(updates.ALL_SOURCES),
        )
    )
    shown.controller._timer.stop()
    shown.show()
    QTest.qWait(50)
    yield shown
    shown._quitting = True
    shown.close()


def test_tall_hidden_section_does_not_stretch_the_mini_window(window: MainWindow) -> None:
    """Содержимое растягивалось ниже края, и кнопка меню уходила за низ окна."""
    window.views["updates"].setMinimumHeight(SIZE["mini_height"] + 300)
    window.navigate("updates")

    window.set_compact(True)
    QTest.qWait(50)

    assert window.height() <= SIZE["mini_height"]
    assert window.layout().minimumSize().height() <= window.height()
    assert window._mini.geometry().bottom() < window.height()


def test_full_view_comes_back_with_its_size(window: MainWindow) -> None:
    before = window.size()

    window.set_compact(True)
    window.set_compact(False)
    QTest.qWait(50)

    assert window.size() == before
    assert window._mini.isHidden()
    assert not window._full_page.isHidden()


def test_section_from_the_mini_window_opens_the_full_view(window: MainWindow) -> None:
    window.set_compact(True)

    window._mini.section_requested.emit("settings")

    assert not window._compact
    assert window._current_section == "settings"


def test_overview_keeps_the_mini_window(window: MainWindow) -> None:
    window.set_compact(True)

    window.navigate("dashboard")

    assert window._compact
