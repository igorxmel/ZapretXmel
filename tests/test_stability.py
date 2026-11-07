"""Журнал стабильности: сервисы, оценка с поправкой на число проверок, часы сбоев и совет."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import paths, repair, stability
from app.ui.controller import Controller

NOW = datetime(2026, 11, 10, 12, 0)


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    core = tmp_path / "core"
    core.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(paths, "core_dir", lambda: core)
    monkeypatch.setattr(paths, "data_dir", lambda: data)
    return tmp_path


def _bat(*names: str) -> None:
    for name in names:
        (paths.core_dir() / f"{name}.bat").write_text(name, encoding="utf-8")


def _checks(name: str, results: list[tuple[list[str], list[str]]], start: datetime) -> None:
    for step, (working, broken) in enumerate(results):
        stability.record(
            name,
            not broken,
            now=start + timedelta(minutes=15 * step),
            working=working,
            broken=broken,
        )


def test_more_checks_mean_more_trust() -> None:
    assert stability.score(5, 5) < stability.score(50, 50) < stability.score(500, 500)
    assert stability.score(5, 5) > stability.UNKNOWN > stability.score(3, 5)
    assert stability.score(2, 2) == stability.UNKNOWN


def test_services_are_counted_separately() -> None:
    good = (["Discord", "YouTube"], [])
    youtube_down = (["Discord"], ["YouTube"])
    _checks("A", [good] * 7 + [youtube_down] * 3, NOW - timedelta(days=1))

    assert stability.services("A", NOW) == {"Discord": (10, 10), "YouTube": (7, 10)}
    assert stability.describe_services("A", NOW) == "Discord 100% · YouTube 70%"


def test_repair_prefers_strategy_that_keeps_the_broken_service() -> None:
    """У «B» в среднем лучше, но YouTube держит «A»: при сломанном YouTube нужна она."""
    _bat("A", "B")
    start = datetime.now() - timedelta(days=1)
    _checks("A", [(["YouTube"], ["Discord"])] * 10, start)
    _checks("B", [(["Discord"], ["YouTube"])] * 2 + [(["Discord", "YouTube"], [])] * 2, start)

    assert repair.shortlist(["A", "B"], [], "", broken=["YouTube"])[0] == "A"


def test_failures_at_night_are_noticed() -> None:
    start = datetime(2026, 11, 1, 0, 0)
    for hour in range(24 * 7):
        moment = start + timedelta(hours=hour)
        stability.record("A", not 20 <= moment.hour < 23, now=moment)

    assert stability.failure_hours(stability.load()["A"].entries(start + timedelta(days=7))) == (
        20,
        23,
    )
    assert stability.describe_hours("A", now=start + timedelta(days=7)) == (
        "в основном с 20:00 до 23:00"
    )


def test_failure_window_covers_all_evening_hours() -> None:
    start = datetime(2026, 11, 1, 0, 0)
    for hour in range(24 * 7):
        moment = start + timedelta(hours=hour)
        stability.record("A", not 19 <= moment.hour < 23, now=moment)

    assert stability.failure_hours(stability.load()["A"].entries(start + timedelta(days=7))) == (
        19,
        23,
    )


def test_scattered_failures_are_not_a_pattern() -> None:
    start = datetime(2026, 11, 1, 0, 0)
    for hour in range(24 * 7):
        stability.record("A", hour % 5 != 0, now=start + timedelta(hours=hour))

    assert stability.failure_hours(stability.load()["A"].entries(start + timedelta(days=7))) is None


def test_marks_need_enough_checks() -> None:
    _checks("A", [(["YouTube"], [])] * 5, NOW - timedelta(hours=2))
    _checks("B", [(["YouTube"], [])] * 2, NOW - timedelta(hours=2))

    assert stability.marks(["A", "B"], NOW) == {"A": "100%"}


def _history(name: str, ok: int, total: int) -> None:
    start = datetime.now() - timedelta(days=2)
    for step in range(total):
        stability.record(name, step < ok, now=start + timedelta(minutes=15 * step))


def test_better_strategy_is_suggested() -> None:
    _bat("A", "B")
    _history("A", 14, 30)
    _history("B", 30, 30)

    assert stability.better_choice("A") == ("B", 100, 47)


def test_good_strategy_gets_no_advice() -> None:
    _bat("A", "B")
    _history("A", 28, 30)
    _history("B", 30, 30)

    assert stability.better_choice("A")[0] == ""


def test_removed_strategy_is_not_suggested() -> None:
    _bat("A", "B")
    _history("A", 10, 30)
    _history("B", 30, 30)
    (paths.core_dir() / "B.bat").unlink()

    assert stability.better_choice("A")[0] == ""


def test_advice_is_given_once() -> None:
    _bat("A", "B")
    _history("A", 10, 30)
    _history("B", 30, 30)
    said: list[str] = []
    controller = SimpleNamespace(
        _advised=set(), advice=SimpleNamespace(emit=said.append)
    )

    Controller._advise(controller, "A")
    Controller._advise(controller, "A")

    assert len(said) == 1
    assert "«B»" in said[0]
