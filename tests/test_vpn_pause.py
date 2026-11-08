"""Пауза обхода на время VPN.

Поводом стал Happ: пока он включён, YouTube не грузится, а Discord и игры
отваливаются через минуту. Ломается ровно то, что в списках обхода, — winws
обрабатывает эти соединения и внутри туннеля. Без обхода через VPN всё работает.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from app.core import vpnpause
from app.core.config import Settings
from app.ui.controller import Controller, Status
from app.ui.views.controls import PowerPair, PowerTile

TUN = "Happ Tunnel"


def _decide(tracker, tunnel="", **kwargs) -> str:
    options = {"enabled": True, "active": True, "paused": False, "busy": False}
    options.update(kwargs)
    return vpnpause.decide(tracker, tunnel, **options)


def test_pause_needs_two_polls_in_a_row() -> None:
    """Переподключение VPN мелькает адаптером на секунду — обход от этого не дёргается."""
    tracker = vpnpause.Tracker()

    assert _decide(tracker, TUN) == ""
    assert _decide(tracker, TUN) == vpnpause.PAUSE


def test_flicker_does_not_pause() -> None:
    tracker = vpnpause.Tracker()

    _decide(tracker, TUN)
    _decide(tracker, "")

    assert _decide(tracker, TUN) == ""


def test_switched_off_never_pauses() -> None:
    tracker = vpnpause.Tracker()
    _decide(tracker, TUN, enabled=False)

    assert _decide(tracker, TUN, enabled=False) == ""


def test_inactive_bypass_is_not_paused() -> None:
    """Выключенный руками обход — не пауза: потом включать его обратно было бы самоуправством."""
    tracker = vpnpause.Tracker()
    _decide(tracker, TUN, active=False)

    assert _decide(tracker, TUN, active=False) == ""


def test_resume_after_tunnel_is_gone_twice() -> None:
    tracker = vpnpause.Tracker()

    assert _decide(tracker, "", active=False, paused=True) == ""
    assert _decide(tracker, "", active=False, paused=True) == vpnpause.RESUME


def test_unticking_during_pause_resumes() -> None:
    tracker = vpnpause.Tracker()

    assert _decide(tracker, TUN, active=False, paused=True, enabled=False) == vpnpause.RESUME


def test_busy_waits() -> None:
    tracker = vpnpause.Tracker()
    _decide(tracker, TUN, busy=True)

    assert _decide(tracker, TUN, busy=True) == ""
    assert _decide(tracker, TUN) == vpnpause.PAUSE


def test_any_vpn_uses_what_was_detected() -> None:
    assert vpnpause.trigger("", TUN) == TUN


def test_chosen_adapter_counts_only_while_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """Выбранный адаптер — даже если автоопределение его не узнало."""
    up = {"Meta": True}
    monkeypatch.setattr(vpnpause, "adapter_up", lambda name: up.get(name, False))

    assert vpnpause.trigger(vpnpause.ADAPTER + "Meta", "") == "Meta"
    up["Meta"] = False
    assert vpnpause.trigger(vpnpause.ADAPTER + "Meta", TUN) == ""


def test_chosen_program_counts_while_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vpnpause, "app_running", lambda path: True)

    assert vpnpause.trigger(vpnpause.APP + r"C:\Happ\Happ.exe", "") == "Happ"


def test_labels() -> None:
    assert vpnpause.label(vpnpause.APP + r"C:\Happ\Happ.exe") == "Программа «Happ.exe»"
    assert vpnpause.label(vpnpause.ADAPTER + "Meta") == "Адаптер «Meta»"


def test_pause_survives_restart_in_settings() -> None:
    assert Settings().pause_for_vpn is False
    assert Settings.from_dict({"vpn_paused": TUN}).vpn_paused == TUN


# --- контроллер -----------------------------------------------------------------


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller(app: QApplication, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Settings, "save", lambda _self: None)
    made = Controller(Settings(pause_for_vpn=True))
    calls: list[str] = []
    state = {"active": True}

    def gather() -> Status:
        return Status(
            core_present=True,
            winws_count=1 if state["active"] else 0,
            active_vpn=state.get("vpn", ""),
            vpn_trigger=state.get("vpn", ""),
            vpn_paused=made.settings.vpn_paused,
        )

    def stop() -> None:
        calls.append("stop")
        state["active"] = False
        made.refresh()

    # Подменяется только сам запуск: решение «включить или на паузу» — настоящее.
    def launch(replace_foreign: bool) -> None:
        calls.append("start")
        state["active"] = True
        made.refresh()

    monkeypatch.setattr(made, "_gather", gather)
    monkeypatch.setattr(made, "stop", stop)
    monkeypatch.setattr(made, "_launch", launch)
    made.calls = calls
    made.state = state
    return made


def test_controller_pauses_and_resumes(controller) -> None:
    controller.state["vpn"] = TUN
    controller.refresh()
    controller.refresh()

    assert controller.calls == ["stop"]
    assert controller.settings.vpn_paused == TUN
    assert controller.status.state_label == "обход на паузе: работает VPN"

    controller.state["vpn"] = ""
    controller.refresh()
    controller.refresh()

    assert controller.calls == ["stop", "start"]
    assert controller.settings.vpn_paused == ""
    assert controller.status.is_active


def _paused(controller) -> None:
    controller.state["vpn"] = TUN
    controller.refresh()
    controller.refresh()
    assert controller.settings.vpn_paused == TUN


def test_pressing_paused_button_turns_bypass_off(controller) -> None:
    """Жёлтая кнопка — «включено, но ждёт»: нажатие выключает, как на зелёной."""
    _paused(controller)

    controller.toggle()
    controller.state["vpn"] = ""
    for _ in range(3):
        controller.refresh()

    assert controller.calls == ["stop"]
    assert controller.settings.vpn_paused == ""
    assert not controller.status.is_active


def test_turning_on_during_vpn_only_pauses(controller) -> None:
    """С галочкой обход при VPN не работает: включение сразу встаёт на паузу."""
    controller.state.update(active=False, vpn=TUN)
    controller.refresh()

    controller.toggle()

    assert controller.calls == []
    assert controller.settings.vpn_paused == TUN

    controller.state["vpn"] = ""
    controller.refresh()
    controller.refresh()
    assert controller.calls == ["start"]
    assert controller.status.is_active


def test_without_the_tick_bypass_works_with_vpn(controller) -> None:
    controller.settings.pause_for_vpn = False
    controller.state.update(active=False, vpn=TUN)
    controller.refresh()

    controller.toggle()
    for _ in range(3):
        controller.refresh()

    assert controller.calls == ["start"]
    assert controller.status.is_active


def test_unticking_during_pause_turns_bypass_on(controller) -> None:
    _paused(controller)

    controller.settings.pause_for_vpn = False
    controller.refresh()

    assert controller.calls == ["stop", "start"]
    assert controller.status.is_active


def test_profiles_wait_for_the_pause(controller, monkeypatch: pytest.MonkeyPatch) -> None:
    started = []
    monkeypatch.setattr(controller, "start_profile", started.append)
    controller.settings.vpn_paused = TUN

    controller._follow_apps("start", "игра")

    assert started == []


def test_paused_button_is_not_shown_as_off(app: QApplication) -> None:
    """Серое кольцо читалось как «выключили», поэтому на паузе кнопка жёлтая."""
    pair = PowerPair.__new__(PowerPair)
    pair.bypass = PowerTile("Обход")
    pair.telegram = PowerTile("Telegram")
    paused = Status(core_present=True, vpn_paused=TUN, vpn_trigger=TUN)
    pair.apply_status(paused)
    assert pair.bypass.button._paused

    pair.apply_status(Status(core_present=True, active_strategy="general", winws_count=1))
    assert not pair.bypass.button._paused
