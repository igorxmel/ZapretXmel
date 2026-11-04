"""Весь путь кнопки «Почини». Нужен QApplication.

Проверки и перебор подменены: важны решения и то, что при неудаче всё возвращается как было.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from app.core.config import Settings
from app.core.probe.autopick import Report, StrategyScore
from app.core.probe.services import CheckResult, ServiceResult
from app.ui import repair as repair_module
from app.ui.controller import Controller, Status
from app.ui.repair import RepairFlow

NAMES = ["a", "b", "c", "d", "e"]


def _check(working: list[str], broken: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        working=working,
        broken=broken,
        everything_works=bool(working) and not broken,
    )


GOOD = _check(["YouTube"], [])
BAD = _check(["Discord"], ["YouTube"])


def _service(name: str, ok: bool) -> ServiceResult:
    return ServiceResult(service=name, checks=[CheckResult(name, ok, "")])


def _score(name: str, works: bool, baseline: bool = False) -> StrategyScore:
    service = _service("YouTube", works)
    return StrategyScore(name=name, ok=int(works), services=[service], is_baseline=baseline)


def _report(names: list[str], winner: str = "", baseline_works=False, cancelled=False) -> Report:
    base = _score("без обхода", baseline_works, baseline=True)
    scores = [_score(name, name == winner) for name in names]
    return Report(
        mode="services",
        started_at="",
        finished_at="",
        checked=[],
        scores=[base, *scores],
        baseline=base,
        cancelled=cancelled,
    )


class Harness:
    """Подменяет проверки и перебор и записывает, что с ними делали."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, checks: list, decide):
        self.checks = list(checks)
        self.passes: list[list[str]] = []
        harness = self

        class FakeQuick(QObject):
            done = pyqtSignal(object)
            failed = pyqtSignal(str)

            def __init__(self, **_):
                super().__init__()

            def start(self):
                self.done.emit(harness.checks.pop(0))

        class FakePicker(QObject):
            progress = pyqtSignal(str)
            done = pyqtSignal(object)
            failed = pyqtSignal(str)

            def __init__(self, specs, **_):
                super().__init__()
                self.names = [spec.name for spec in specs]

            def isRunning(self):  # noqa: N802 — имя задано Qt
                return False

            def start(self):
                harness.passes.append(self.names)
                self.done.emit(decide(self.names))

        monkeypatch.setattr(repair_module, "QuickCheckWorker", FakeQuick)
        monkeypatch.setattr(repair_module, "AutoPickWorker", FakePicker)
        monkeypatch.setattr(repair_module, "save_report", lambda _report: None)
        monkeypatch.setattr(repair_module.services, "discover", lambda: [])
        monkeypatch.setattr(
            repair_module.strategies,
            "load_all",
            lambda: [SimpleNamespace(name=name) for name in NAMES],
        )
        monkeypatch.setattr(
            repair_module.QTimer, "singleShot", lambda _ms, call: call()
        )
        monkeypatch.setattr(repair_module.repair.stability, "load", dict)


@pytest.fixture
def flow(monkeypatch: pytest.MonkeyPatch) -> RepairFlow:
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(Settings, "save", lambda _self: None)
    monkeypatch.setattr("app.core.stability.record", lambda *_, **__: None)
    controller = Controller(Settings(selected_strategy="a"))
    controller.status = Status(core_present=True, winws_count=1, active_strategy="a")
    controller.log = []

    def stop():
        controller.log.append("stop")
        controller.status = Status(core_present=True)

    def start():
        controller.log.append(f"start {controller.settings.selected_strategy}")
        controller.status = Status(
            core_present=True,
            winws_count=1,
            active_strategy=controller.settings.selected_strategy,
        )

    monkeypatch.setattr(controller, "stop", stop)
    monkeypatch.setattr(controller, "start", start)
    monkeypatch.setattr(controller, "refresh", lambda: controller.status)
    return RepairFlow(controller)


def _answers(flow: RepairFlow) -> list[str]:
    answers: list[str] = []
    flow.finished.connect(lambda text, _colour: answers.append(text))
    return answers


def test_working_setup_is_left_alone(flow, monkeypatch) -> None:
    Harness(monkeypatch, [GOOD], lambda names: _report(names))
    answers = _answers(flow)

    flow.start()

    assert "чинить нечего" in answers[0]
    assert flow.controller.log == []


def test_good_candidate_from_the_short_list_is_enabled(flow, monkeypatch) -> None:
    harness = Harness(monkeypatch, [BAD, GOOD], lambda names: _report(names, winner=names[0]))
    answers = _answers(flow)

    flow.start()

    assert len(harness.passes) == 1, "полный перебор не нужен"
    assert "a" not in harness.passes[0], "текущая только что не прошла проверку"
    assert flow.controller.log == ["stop", f"start {harness.passes[0][0]}"]
    assert "всё работает" in answers[0]
    assert not flow.running


def test_full_pass_runs_only_when_the_short_list_failed(flow, monkeypatch) -> None:
    def decide(names):
        return _report(names, winner="e" if "e" in names else "")

    harness = Harness(monkeypatch, [BAD, GOOD], decide)
    # e в короткий список не входит: туда попадают первые по порядку.
    flow.start()

    assert len(harness.passes) == 2
    assert not set(harness.passes[0]) & set(harness.passes[1]), "дважды мерить незачем"
    assert flow.controller.log[-1] == "start e"


def test_nothing_helped_brings_back_the_old_strategy(flow, monkeypatch) -> None:
    Harness(monkeypatch, [BAD], lambda names: _report(names))
    answers = _answers(flow)

    flow.start()

    assert flow.controller.log == ["stop", "start a"]
    assert "Ни одна стратегия" in answers[0]


def test_cancel_brings_back_the_old_strategy(flow, monkeypatch) -> None:
    Harness(monkeypatch, [BAD], lambda names: _report(names, cancelled=True))
    answers = _answers(flow)

    flow.start()

    assert flow.controller.log == ["stop", "start a"]
    assert "остановлена" in answers[0]


def test_bypass_that_was_off_stays_off_after_failure(flow, monkeypatch) -> None:
    flow.controller.status = Status(core_present=True)
    Harness(monkeypatch, [BAD], lambda names: _report(names))

    flow.start()

    assert flow.controller.log == ["stop"]


def test_nothing_blocked_is_said_plainly(flow, monkeypatch) -> None:
    Harness(monkeypatch, [BAD], lambda names: _report(names, baseline_works=True))
    answers = _answers(flow)

    flow.start()

    assert "без обхода" in answers[0]
    assert flow.controller.log == ["stop", "start a"]


def test_partial_result_is_reported_honestly(flow, monkeypatch) -> None:
    Harness(monkeypatch, [BAD, BAD], lambda names: _report(names, winner=names[0]))
    answers = _answers(flow)

    flow.start()

    assert "не работает: YouTube" in answers[0]


@pytest.mark.parametrize(
    ("status", "picking", "word"),
    [
        (Status(core_present=False), False, "ядро"),
        (Status(core_present=True, active_vpn="Meta"), False, "Meta"),
        (Status(core_present=True), True, "подбор"),
    ],
)
def test_refuses_when_it_makes_no_sense(flow, status, picking, word) -> None:
    flow.controller.status = status
    flow.controller.picking = picking

    assert word in flow.refusal()


def test_watch_stays_quiet_while_repairing(flow, monkeypatch) -> None:
    """Починка сама гасит обход, и сторож принял бы это за поломку."""
    created: list[bool] = []
    monkeypatch.setattr(
        "app.ui.workers.QuickCheckWorker", lambda **_: created.append(True)
    )
    flow.controller._repair = flow
    flow.running = True

    flow.controller.watch_now()

    assert created == []
