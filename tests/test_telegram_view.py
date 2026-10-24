"""Надпись о подключении на вкладке Telegram.

Нужен QApplication. Проверяется то, что ломалось: надпись считалась один раз при
открытии вкладки и после подключения клиента оставалась жёлтой.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from app.core.config import Settings
from app.ui.controller import Controller, Status
from app.ui.theme.tokens import COLORS
from app.ui.views.telegram import TelegramView


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app: QApplication) -> TelegramView:
    controller = Controller(Settings())
    view = TelegramView(controller)
    controller.status_changed.connect(view.on_status)
    return view


def colour_of(view: TelegramView) -> str:
    return view._connection.styleSheet()


def test_label_turns_green_when_telegram_connects_while_the_tab_is_open(view) -> None:
    """Открыли вкладку, увидели «ещё не подключился», нажали «Открыть в Telegram»."""
    view.controller.status_changed.emit(Status(telegram_running=True, telegram_connected=False))
    assert view._connection.isVisibleTo(view)
    assert COLORS["warning"] in colour_of(view)
    assert "ещё не подключился" in view._connection.text()

    view.controller.status_changed.emit(Status(telegram_running=True, telegram_connected=True))
    assert COLORS["success"] in colour_of(view)
    assert "подключён" in view._connection.text()


def test_label_hides_when_the_proxy_stops(view) -> None:
    view.controller.status_changed.emit(Status(telegram_running=True, telegram_connected=False))
    view.controller.status_changed.emit(Status(telegram_running=False, telegram_connected=False))

    assert not view._connection.isVisibleTo(view)


def test_label_does_not_ask_the_system_itself(view, monkeypatch: pytest.MonkeyPatch) -> None:
    """Список соединений читается долго: в потоке интерфейса его запрашивать нельзя."""
    from app.core import telegram

    def forbidden(*args, **kwargs):
        raise AssertionError("синхронный опрос соединений в потоке интерфейса")

    monkeypatch.setattr(telegram, "has_clients", forbidden)

    view.controller.status_changed.emit(Status(telegram_running=True, telegram_connected=True))
    assert COLORS["success"] in colour_of(view)
