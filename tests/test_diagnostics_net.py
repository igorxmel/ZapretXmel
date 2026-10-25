"""Сетевые проверки на экране диагностики: поле для своего сайта и подсказки.

Нужен QApplication, поэтому тест живёт отдельно.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from app.core.config import Settings
from app.ui.controller import Controller
from app.ui.views.diagnostics import DiagnosticsView


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app: QApplication) -> DiagnosticsView:
    return DiagnosticsView(Controller(Settings()))


def tip(view: DiagnosticsView, index: int) -> str:
    return view._net_buttons[index].toolTip()


def test_every_button_names_its_console_command(view: DiagnosticsView) -> None:
    for index in range(5):
        assert "В консоли:" in tip(view, index)


def test_commands_without_a_site_are_exact(view: DiagnosticsView) -> None:
    assert "ipconfig /flushdns" in tip(view, 0)
    assert "netsh interface ipv4 show subinterfaces" in tip(view, 4)


def test_typed_site_goes_into_the_tooltip_live(view: DiagnosticsView) -> None:
    assert "<сайт>" in tip(view, 3)

    view._site.setText("https://www.Instagram.com/x")

    assert "tracert -d -h 12 -w 800 www.instagram.com" in tip(view, 3)
    assert "nslookup www.instagram.com" in tip(view, 1)
    assert "https://www.instagram.com" in tip(view, 2)


def test_something_that_is_not_an_address_does_not_start_a_check(
    view: DiagnosticsView,
) -> None:
    view._site.setText("-h 1 & calc")

    view._net_buttons[3].click()

    assert "не похоже на адрес" in view._net_result.toPlainText()
    assert all(button.isEnabled() for button in view._net_buttons)
    assert getattr(view, "_net_task", None) is None


def test_the_site_reaches_the_worker_normalised(
    view: DiagnosticsView, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import nettools

    seen: list[str] = []

    class Stub:
        def __init__(self, func):
            self.func = func
            self.done = type("S", (), {"connect": lambda *a: None})()
            self.failed = type("S", (), {"connect": lambda *a: None})()

        def start(self):
            seen.append(self.func())

    monkeypatch.setattr("app.ui.views.diagnostics.Task", Stub)
    monkeypatch.setattr(nettools, "trace", lambda host: host)

    view._site.setText("  HTTPS://Instagram.com/ ")
    view._net_buttons[3].click()

    assert seen == ["instagram.com"]
