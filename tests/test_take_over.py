"""Мьютекс занят: ждать, сменить или спросить.

После «Обновить и перезапустить» прежний экземпляр закрывался дольше пяти
секунд, и новый спрашивал «прошлый запуск завис», хотя завис он только с
виду — он сам попросил заменить себя.
"""

from __future__ import annotations

import sys

import pytest

import app.__main__ as main
from app.core import singleton


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    log: list[str] = []
    monkeypatch.setattr(singleton, "focus_existing", lambda: log.append("focus") or False)
    monkeypatch.setattr(singleton, "terminate_others", lambda: log.append("terminate") or 1)
    monkeypatch.setattr(singleton, "acquire", lambda: log.append("acquire") or True)
    monkeypatch.setattr(main, "revive_stuck_instance", lambda: log.append("ask") or False)
    return log


def _argv(monkeypatch, *flags: str) -> None:
    monkeypatch.setattr(sys, "argv", ["ZapretXmel.exe", *flags])


def test_after_update_waits_longer(calls, monkeypatch) -> None:
    waited = []
    monkeypatch.setattr(
        main, "_wait_for_predecessor", lambda restarted, wait: waited.append(wait) or True
    )
    _argv(monkeypatch, singleton.RESTART_FLAG)

    assert main.take_over()
    assert waited == [main.RESTARTED_WAIT]
    assert "focus" not in calls


def test_after_update_slow_predecessor_is_replaced_without_asking(calls, monkeypatch) -> None:
    monkeypatch.setattr(main, "_wait_for_predecessor", lambda restarted, wait: False)
    _argv(monkeypatch, singleton.RESTART_FLAG)

    assert main.take_over()
    assert calls == ["terminate", "acquire"]


def test_plain_launch_still_asks_about_a_hung_instance(calls, monkeypatch) -> None:
    waited = []
    monkeypatch.setattr(
        main, "_wait_for_predecessor", lambda restarted, wait: waited.append(wait) or False
    )
    _argv(monkeypatch)

    assert not main.take_over()
    assert waited == [main.PREDECESSOR_WAIT]
    assert calls == ["focus", "ask"]


def test_plain_launch_shows_the_running_window(calls, monkeypatch) -> None:
    monkeypatch.setattr(singleton, "focus_existing", lambda: True)
    _argv(monkeypatch)

    assert not main.take_over()
    assert calls == []
