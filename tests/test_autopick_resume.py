"""Время в подборе, перепроверка лидеров и продолжение прерванного подбора."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.probe import autopick, http
from app.core.probe.services import CheckResult, ServiceResult


def _score(name: str, *checks: tuple[bool, float]) -> autopick.StrategyScore:
    results = [
        ServiceResult(
            service=f"s{i}",
            checks=[CheckResult(f"s{i}", ok, "", target=f"s{i}", elapsed_ms=ms)],
        )
        for i, (ok, ms) in enumerate(checks)
    ]
    return autopick.build_services_score(name, results, [])


# --- время -------------------------------------------------------------------


def test_curl_time_is_read_in_milliseconds() -> None:
    assert http._parse_write_out("200 0.123456") == ("200", 123.456)
    assert http._parse_write_out("000") == ("000", None)
    assert http._parse_write_out("") == ("", None)


def test_time_column_is_filled_in_services_mode() -> None:
    """Колонка «Время» была, но в режиме по сервисам в ней всегда стоял прочерк."""
    score = _score("a", (True, 100.0), (True, 300.0), (False, 6000.0))

    assert score.median_ms == 200.0, "таймаут непрошедшей пробы о скорости не говорит"


def test_faster_strategy_wins_a_tie() -> None:
    slow = _score("slow", (True, 400.0), (True, 400.0))
    fast = _score("fast", (True, 90.0), (True, 110.0))

    assert min([slow, fast], key=lambda s: s.sort_key).name == "fast"


# --- перепроверка лидеров -----------------------------------------------------


def test_a_check_counts_only_if_it_passed_both_times() -> None:
    first = _score("a", (True, 100.0), (True, 200.0))
    second = _score("a", (True, 120.0), (False, 6000.0))

    merged = autopick.combine(first, second)

    assert merged.ok == 1 and merged.error == 1
    assert merged.working_services == ["s0"]
    assert merged.median_ms == 110.0


def test_only_close_leaders_are_rechecked() -> None:
    report = autopick.Report("services", "", "", ["s0", "s1"])
    report.scores = [
        _score("a", (True, 1), (True, 1)),
        _score("b", (True, 1), (True, 1)),
        _score("c", (True, 1), (False, 1)),
    ]

    assert [s.name for s in autopick.leaders(report)] == ["a", "b"]


def test_clear_winner_is_not_rechecked() -> None:
    report = autopick.Report("services", "", "", ["s0", "s1"])
    report.scores = [_score("a", (True, 1), (True, 1)), _score("b", (True, 1), (False, 1))]

    assert autopick.leaders(report) == []


# --- продолжение подбора ------------------------------------------------------


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(autopick.paths, "data_dir", lambda: tmp_path)
    return tmp_path


def _report(*scores: autopick.StrategyScore) -> autopick.Report:
    report = autopick.Report("services", "", "", ["s0", "s1"])
    report.scores = list(scores)
    return report


def test_progress_survives_a_restart(data) -> None:
    autopick.save_progress(_report(_score("a", (True, 80.0), (False, 0.0))), ["a", "b", "c"])

    unfinished = autopick.load_progress(["c", "b", "a"])

    assert unfinished is not None
    assert (unfinished.done, unfinished.total) == (1, 3)
    assert unfinished.checked == ["s0", "s1"]
    restored = unfinished.scores[0]
    assert restored.name == "a" and restored.ok == 1 and restored.median_ms == 80.0
    assert restored.services[0].checks[0].elapsed_ms == 80.0


def test_changed_strategies_start_over(data) -> None:
    """Обновилось ядро или добавили свою стратегию — старые итоги уже про другое."""
    autopick.save_progress(_report(_score("a", (True, 1))), ["a", "b"])

    assert autopick.load_progress(["a", "b", "новая"]) is None
    assert not autopick.progress_file().exists()


def test_day_old_progress_is_dropped(data) -> None:
    autopick.save_progress(_report(_score("a", (True, 1))), ["a", "b"])
    tomorrow = datetime.now() + timedelta(hours=autopick.PROGRESS_MAX_AGE_HOURS + 1)

    assert autopick.load_progress(["a", "b"], now=tomorrow) is None


def test_broken_file_is_not_a_crash(data) -> None:
    autopick.progress_file().write_text("{не json", encoding="utf-8")

    assert autopick.load_progress(["a"]) is None


def test_resume_skips_what_was_already_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    tried: list[str] = []
    monkeypatch.setattr(autopick.winws, "find_instances", lambda: [])
    monkeypatch.setattr(autopick.winws, "kill_all", lambda *a, **k: 0)
    monkeypatch.setattr(autopick.ipset, "status", lambda: "any")
    picker = autopick.AutoPicker()
    baseline = _score(autopick.BASELINE_NAME, (False, 0.0))
    baseline.is_baseline = True
    monkeypatch.setattr(picker, "_measure", lambda *a, **k: baseline)

    def run_one(spec, *_args):
        tried.append(spec.name)
        return _score(spec.name, (spec.name == "c", 50.0))

    monkeypatch.setattr(picker, "_run_one", run_one)
    saved: list[int] = []

    report = picker.run(
        [SimpleNamespace(name=n) for n in ("a", "b", "c")],
        done=[_score("a", (False, 0.0)), _score("b", (False, 0.0))],
        on_checkpoint=lambda r: saved.append(len(r.strategies)),
    )

    assert tried == ["c"]
    assert report.resumed == 2
    assert [s.name for s in report.strategies] == ["a", "b", "c"]
    assert saved == [1, 2, 3], "ход сохраняется после каждой стратегии"
    assert report.best is not None and report.best.name == "c"


def test_best_result_gets_its_own_banner() -> None:
    """Итог — плашкой со счётом и кнопкой «Применить», а не только строкой таблицы."""
    from PyQt6.QtWidgets import QApplication

    from app.core.config import Settings
    from app.ui.controller import Controller
    from app.ui.views.autopick import AutoPickView

    app = QApplication.instance() or QApplication([])  # noqa: F841 — без ссылки Qt падает
    view = AutoPickView(Controller(Settings()))
    report = autopick.Report("services", "", "", ["s0", "s1"])
    report.baseline = _score(autopick.BASELINE_NAME, (False, 0.0), (False, 0.0))
    report.baseline.is_baseline = True
    report.scores = [report.baseline, _score("winner", (True, 90.0), (True, 110.0))]

    view._show_best(report)

    assert not view._banner.isHidden()
    assert view._best_score.text() == "2/2"
    assert "winner" in view._best_name.text() and "100 мс" in view._best_name.text()
    assert view._apply_button.parent() is view._banner
