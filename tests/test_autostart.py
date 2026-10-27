"""Автозапуск не должен зависеть от того, подключена ли зарядка."""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET

import pytest

from app.core import autostart

NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"


def _settings() -> dict[str, str]:
    root = ET.fromstring(autostart.task_xml().replace('encoding="UTF-16"', ""))
    return {child.tag.removeprefix(NS): (child.text or "") for child in root.find(f"{NS}Settings")}


def test_task_ignores_battery_state() -> None:
    """На ноутбуке без зарядки программа не запускалась, а при отключении гасла."""
    settings = _settings()

    assert settings["DisallowStartIfOnBatteries"] == "false"
    assert settings["StopIfGoingOnBatteries"] == "false"


def test_task_is_not_killed_after_three_days() -> None:
    assert _settings()["ExecutionTimeLimit"] == "PT0S"


def test_task_runs_with_highest_rights() -> None:
    assert "<RunLevel>HighestAvailable</RunLevel>" in autostart.task_xml()


def test_task_is_valid_xml_with_awkward_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autostart, "_command", lambda: (r"C:\Мои & <файлы>\Z.exe", ""))

    root = ET.fromstring(autostart.task_xml().replace('encoding="UTF-16"', ""))

    assert root.find(f".//{NS}Command").text == r"C:\Мои & <файлы>\Z.exe"


OLD_TASK = "<Settings><DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries></Settings>"
NEW_TASK = autostart.task_xml()


@pytest.mark.parametrize(("xml", "broken"), [(OLD_TASK, True), (NEW_TASK, False), ("", True)])
def test_old_tasks_are_recognised(xml: str, broken: bool) -> None:
    assert autostart._stops_on_battery(xml) is broken


def _fake_run(monkeypatch: pytest.MonkeyPatch, code: int, out: str) -> None:
    monkeypatch.setattr(
        autostart, "_run", lambda args: subprocess.CompletedProcess(args, code, out, "")
    )


def test_missing_task_is_not_created_by_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    """Автозапуск, которого человек не включал, чинить не нужно."""
    _fake_run(monkeypatch, 1, "")
    monkeypatch.setattr(autostart.elevation, "is_admin", lambda: True)
    monkeypatch.setattr(autostart, "set_enabled", lambda *_: pytest.fail("задачи нет"))

    autostart.repair()


def test_old_task_is_recreated(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_run(monkeypatch, 0, OLD_TASK)
    monkeypatch.setattr(autostart.elevation, "is_admin", lambda: True)
    calls: list[bool] = []
    monkeypatch.setattr(autostart, "set_enabled", lambda wanted: calls.append(wanted) or True)

    autostart.repair()

    assert calls == [True]


def test_fixed_task_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_run(monkeypatch, 0, NEW_TASK)
    monkeypatch.setattr(autostart.elevation, "is_admin", lambda: True)
    monkeypatch.setattr(autostart, "set_enabled", lambda *_: pytest.fail("уже исправлена"))

    autostart.repair()
