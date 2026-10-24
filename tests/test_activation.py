"""Слушатель повторного запуска: сигнал из потока должен дойти до окна.

Нужен QApplication, поэтому тест живёт отдельно. Проверяется то, что здесь легко
сломать молча: сигнал приходит из потока, который Qt не создавал, и дойти до
потока интерфейса он обязан через очередь, а не выполниться на месте.
"""

from __future__ import annotations

import threading
import time

import pytest
from PyQt6.QtWidgets import QApplication

from app.core import singleton
from app.ui.activation import ActivationListener


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_signal_from_the_worker_thread_reaches_the_gui_thread(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    pending = [True]

    def fake_wait(timeout_ms: int) -> bool:
        if pending:
            pending.pop()
            return True
        time.sleep(timeout_ms / 1000)
        return False

    monkeypatch.setattr(singleton, "wait_activation", fake_wait)

    received: list[int] = []
    listener = ActivationListener()
    listener.activated.connect(lambda: received.append(threading.get_ident()))
    listener.start()

    deadline = time.monotonic() + 3
    while not received and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    listener.stop()

    assert len(received) == 1, "просьба показать окно не дошла"
    assert received[0] == threading.get_ident(), "окно тронули не из потока интерфейса"


def test_stop_ends_the_thread(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(singleton, "wait_activation", lambda ms: time.sleep(0.01) or False)

    listener = ActivationListener()
    listener.start()
    listener.stop()
    listener._thread.join(timeout=2)

    assert not listener._thread.is_alive()
