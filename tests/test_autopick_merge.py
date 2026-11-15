"""Сборка на экране подбора: от кнопки до решения, остаётся ли она в списке.

Нужен QApplication. Сами замеры подменяются: здесь важно, что сборка меряется вместе с
исходными и что файл не остаётся в списке, если она не лучше них.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QLabel

from app.core import merge, paths, strategies
from app.core.config import Settings
from app.core.merge import plan_from_winners
from app.core.probe.autopick import Report, StrategyScore
from app.ui import dialogs
from app.ui.controller import Controller
from app.ui.views.autopick import RESULT_LIFETIME_NOTE, START_TEXT, AutoPickView

FIXTURES = Path(__file__).parent / "fixtures" / "bundle_1_10_3"
HOSTS = {"Discord": ["discord.com"], "YouTube": ["www.youtube.com"]}
LISTS = {"list-general.txt": "discord.com\n", "list-google.txt": "youtube.com\n"}


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AutoPickView:
    root = tmp_path / "Program Files" / "core"
    shutil.copytree(FIXTURES, root)
    (root / "lists").mkdir(exist_ok=True)
    for name, text in LISTS.items():
        (root / "lists" / name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(paths, "core_dir", lambda: root)
    monkeypatch.setattr(merge, "service_hosts", lambda: HOSTS)
    shown = AutoPickView(Controller(Settings()))
    shown.reload()
    shown.launched = []
    monkeypatch.setattr(
        shown, "_launch", lambda specs, _mode, _chosen: shown.launched.extend(specs)
    )
    monkeypatch.setattr("app.ui.views.autopick.save_report", lambda _report: Path("отчёт.json"))
    return shown


def _click_merge(view: AutoPickView) -> None:
    view._plan = plan_from_winners({"Discord": "general (ALT12)", "YouTube": "general"})
    view._merge_best()


def _measured(view: AutoPickView, built_ok: int) -> Report:
    names = [spec.name for spec in view.launched]
    oks = [5] * (len(names) - 1) + [built_ok]
    return Report(
        mode="services",
        started_at="",
        finished_at="",
        checked=[],
        scores=[StrategyScore(name=name, ok=ok) for name, ok in zip(names, oks, strict=True)],
    )


def _names() -> list[str]:
    return [path.stem for path in strategies.discover()]


def test_build_is_measured_after_its_sources(view: AutoPickView) -> None:
    """При равенстве побеждает мерившаяся раньше, то есть исходная."""
    _click_merge(view)

    names = [spec.name for spec in view.launched]
    assert set(names[:-1]) == {"general", "general (ALT12)"}
    assert merge.is_merged(names[-1])


def test_better_build_stays_in_the_list(view: AutoPickView) -> None:
    _click_merge(view)
    name = view.launched[-1].name

    view._finish(_measured(view, built_ok=8))

    assert name in _names()
    assert "лучше исходных" in view._verdict.text()
    assert view._report.best.name == name


@pytest.mark.parametrize("built_ok", [5, 3])
def test_build_that_is_not_better_leaves_the_list(view: AutoPickView, built_ok: int) -> None:
    _click_merge(view)
    name = view.launched[-1].name
    assert name in _names()

    view._finish(_measured(view, built_ok))

    assert name not in _names()
    assert "не добавлена" in view._verdict.text()


def test_failed_measurement_leaves_no_file(view: AutoPickView) -> None:
    _click_merge(view)
    name = view.launched[-1].name

    view._fail("сломалось")

    assert name not in _names()


def test_measured_build_does_not_offer_merging_again(view: AutoPickView) -> None:
    _click_merge(view)

    view._finish(_measured(view, built_ok=8))

    assert view._merge_button.isHidden()


def test_explanations_live_behind_the_question_mark(view: AutoPickView, monkeypatch) -> None:
    """Абзацы «что делает, как считает» стояли над кнопками и прятали главное."""
    shown = []
    monkeypatch.setattr(dialogs, "tell", lambda *args, **_: shown.append(args))

    texts = " ".join(label.text() for label in view.findChildren(QLabel))
    assert "Как считает" not in texts and RESULT_LIFETIME_NOTE not in texts

    view._show_help()
    assert shown and RESULT_LIFETIME_NOTE in shown[0][-1] and "Discord" in shown[0][-1]


def test_own_targets_are_a_plus_next_to_the_services(view: AutoPickView) -> None:
    view._rebuild_chips()

    assert view._add_targets.text() == "+"
    row = [view._chips_row.itemAt(i).widget() for i in range(view._chips_row.count())]
    assert row.index(view._add_targets) == len(view._service_chips)


def test_one_button_starts_and_stops(view: AutoPickView) -> None:
    view._set_running(True)
    assert view._start_button.text() == "Остановить" and view._start_button.isEnabled()

    view._set_running(False)
    assert view._start_button.text() == START_TEXT


def test_start_goes_all_the_way_to_the_worker(view: AutoPickView, monkeypatch) -> None:
    """Кнопка проходит запуск целиком, а не только первые шаги.

    Поле `_stops_early` однажды перекрыло одноимённый метод, и любой запуск падал с
    «'bool' object is not callable» — тесты этого не видели: до работника не доходил ни один.
    """
    from app.core import strategies
    from app.core.diagnostics import vpn
    from app.ui.views import autopick

    launched = []

    class Worker:
        def __init__(self, specs, **kwargs):
            launched.append(([spec.name for spec in specs], kwargs.get("stop_when")))
            noop = type("Signal", (), {"connect": lambda *_: None})()
            self.progress = self.strategy_done = self.done = self.failed = noop

        def start(self):
            pass

    monkeypatch.setattr(autopick, "AutoPickWorker", Worker)
    monkeypatch.setattr(vpn, "detect_fast", lambda: None)
    monkeypatch.setattr(
        strategies, "load_all", lambda *a, **k: [type("S", (), {"name": n})() for n in "ab"]
    )
    # Заготовка этих тестов подменяет _launch — здесь нужен настоящий.
    monkeypatch.setattr(view, "_launch", AutoPickView._launch.__get__(view))
    view._rebuild_chips()

    for early in (False, True):
        view._stop_early.setChecked(early)
        view._start_now()
        assert view._start_button.text() == "Остановить"
        view._set_running(False)

    assert [stop is not None for _, stop in launched] == [False, True]
