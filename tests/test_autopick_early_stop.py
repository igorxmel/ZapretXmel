"""Подбор с остановкой на первой стратегии, где работает всё.

Полный прогон 22 стратегий — около минуты. Если нужна просто рабочая, быстрее
начать с тех, что работали раньше, и остановиться на первой подошедшей.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import repair, stability
from app.core.probe import autopick
from app.core.probe.services import CheckResult, ServiceResult


def _score(name: str, *working: bool) -> autopick.StrategyScore:
    services = [
        ServiceResult(service=f"s{i}", checks=[CheckResult(f"s{i}", ok, "", target=f"s{i}")])
        for i, ok in enumerate(working)
    ]
    return autopick.StrategyScore(name=name, ok=sum(working), services=services)


@pytest.fixture
def picker(monkeypatch: pytest.MonkeyPatch):
    """Подбор без winws и сети: исход каждой стратегии задаёт тест."""
    outcomes: dict[str, autopick.StrategyScore] = {}
    tried: list[str] = []
    monkeypatch.setattr(autopick.winws, "find_instances", lambda: [])
    monkeypatch.setattr(autopick.winws, "kill_all", lambda *a, **k: 0)
    monkeypatch.setattr(autopick.ipset, "status", lambda: "any")

    made = autopick.AutoPicker()
    baseline = _score(autopick.BASELINE_NAME, False, False)
    baseline.is_baseline = True
    monkeypatch.setattr(made, "_measure", lambda *a, **k: baseline)

    def run_one(spec, *_args):
        tried.append(spec.name)
        return outcomes[spec.name]

    monkeypatch.setattr(made, "_run_one", run_one)
    made.outcomes, made.tried = outcomes, tried
    return made


def _specs(*names: str) -> list:
    return [SimpleNamespace(name=name) for name in names]


def _all_work(score: autopick.StrategyScore) -> bool:
    return repair.fully_works(score)


def test_stops_on_the_first_strategy_where_everything_works(picker) -> None:
    picker.outcomes.update(
        a=_score("a", True, False), b=_score("b", True, True), c=_score("c", True, True)
    )

    report = picker.run(_specs("a", "b", "c"), stop_when=_all_work)

    assert picker.tried == ["a", "b"]
    assert report.stopped_early
    assert report.best.name == "b"
    assert "проверено 2 из 3" in report.verdict


def test_without_the_tick_every_strategy_is_tried(picker) -> None:
    picker.outcomes.update(a=_score("a", True, True), b=_score("b", True, True))

    report = picker.run(_specs("a", "b"))

    assert picker.tried == ["a", "b"]
    assert not report.stopped_early


def test_nothing_fully_works_means_a_full_pass(picker) -> None:
    picker.outcomes.update(a=_score("a", True, False), b=_score("b", False, True))

    report = picker.run(_specs("a", "b"), stop_when=_all_work)

    assert picker.tried == ["a", "b"]
    assert not report.stopped_early


def test_last_strategy_succeeding_is_not_an_early_stop(picker) -> None:
    picker.outcomes.update(a=_score("a", False, False), b=_score("b", True, True))

    report = picker.run(_specs("a", "b"), stop_when=_all_work)

    assert not report.stopped_early
    assert "проверено" not in report.verdict


def test_order_puts_favorites_then_the_most_reliable_first(monkeypatch) -> None:
    reliability = {"steady": 0.9, "shaky": 0.2, "unknown": 0.5, "liked": 0.1}
    monkeypatch.setattr(
        stability,
        "rank",
        lambda names, broken=None: sorted(names, key=lambda n: -reliability.get(n, 0.5)),
    )

    names = ["shaky", "unknown", "steady", "liked"]

    assert repair.ordered(names, ["liked"]) == ["liked", "steady", "unknown", "shaky"]
    # «Починить» берёт то же начало списка.
    assert repair.shortlist(names, ["liked"], current="") == ["liked", "steady", "unknown"]


def test_timing_estimates_from_strategies_already_done() -> None:
    from app.ui.views.autopick import timing

    assert timing(5, 0, 22, False) == "Прошло 0:05"
    assert timing(10, 5, 22, False) == "Прошло 0:10 · осталось около 0:34"
    # С остановкой на первой рабочей оценка — потолок: подбор может кончиться раньше.
    assert timing(10, 5, 22, True) == "Прошло 0:10 · осталось не больше 0:34"
    assert timing(70, 22, 22, False) == "Прошло 1:10"
