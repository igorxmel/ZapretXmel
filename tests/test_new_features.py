"""Журнал стабильности, решения починки, перенос настроек и отчёт о поломке."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from app.core import appprofile, backup, paths, repair, report, stability
from app.core.config import Settings
from app.core.probe.autopick import Report, StrategyScore
from app.core.probe.services import CheckResult, ServiceResult
from app.ui.controller import Controller, Status


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    core = tmp_path / "Program Files" / "core"
    (core / "lists").mkdir(parents=True)
    (core / "utils").mkdir()
    (core / "bin").mkdir()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(paths, "core_dir", lambda: core)
    monkeypatch.setattr(paths, "core_lists", lambda: core / "lists")
    monkeypatch.setattr(paths, "core_utils", lambda: core / "utils")
    monkeypatch.setattr(paths, "data_dir", lambda: data)
    monkeypatch.setattr(paths, "config_file", lambda: data / "config.json")
    return tmp_path


# --- журнал -----------------------------------------------------------------


def test_record_counts_checks(home: Path) -> None:
    stability.record("A", True)
    stability.record("A", False)

    item = stability.load()["A"]
    assert (item.checks, item.passed) == (2, 1)


def test_failure_resets_the_streak(home: Path) -> None:
    stability.record("A", True, now=datetime(2026, 11, 1))
    stability.record("A", False, now=datetime(2026, 11, 2))

    assert stability.load()["A"].working_since == ""


def test_streak_is_described(home: Path) -> None:
    stability.record("A", True, now=datetime(2026, 11, 1))

    assert "без сбоев 3 дн." in stability.describe("A", now=datetime(2026, 11, 4))


def test_unknown_strategy_is_described_honestly(home: Path) -> None:
    assert stability.describe("нет такой") == "пока не проверялась"


def test_rank_puts_proven_first_and_bad_last(home: Path) -> None:
    for _ in range(stability.ENOUGH_CHECKS):
        stability.record("хорошая", True)
        stability.record("плохая", False)

    assert stability.rank(["плохая", "новая", "хорошая"]) == ["хорошая", "новая", "плохая"]


def test_few_checks_prove_nothing(home: Path) -> None:
    stability.record("A", False)

    assert stability.rank(["A", "B"]) == ["A", "B"]


def test_old_checks_drop_out_of_the_window(home: Path) -> None:
    """Вечный счёт держал оценку стратегии, переставшей работать, на сотнях старых удач."""
    for day in range(1, 11):
        stability.record("A", True, now=datetime(2026, 10, day))
    stability.record("A", False, now=datetime(2026, 11, 1))

    assert stability.load()["A"].recent(datetime(2026, 11, 1)) == [False]
    assert stability.describe("A", now=datetime(2026, 11, 1)).startswith("прошла 0 из 1")


def test_changed_strategy_file_starts_a_new_journal(home: Path) -> None:
    bat = paths.core_dir() / "A.bat"
    bat.write_text("старые аргументы", encoding="utf-8")
    for _ in range(stability.ENOUGH_CHECKS):
        stability.record("A", False)

    bat.write_text("новые аргументы", encoding="utf-8")

    assert stability.describe("A") == "пока не проверялась"
    assert stability.rank(["B", "A"]) == ["B", "A"], "неизвестная, а не плохая"
    stability.record("A", True)
    assert stability.load()["A"].checks == 1


def test_journal_of_old_versions_is_started_over(home: Path) -> None:
    (paths.data_dir() / stability.FILENAME).write_text(
        '{"A": {"checks": 300, "passed": 290, "working_since": ""}}', encoding="utf-8"
    )

    assert stability.load() == {}


def test_entries_are_capped(home: Path) -> None:
    for _ in range(stability.MAX_ENTRIES + 5):
        stability.record("A", True)

    assert stability.load()["A"].checks == stability.MAX_ENTRIES


def test_broken_journal_does_not_break_anything(home: Path) -> None:
    (paths.data_dir() / stability.FILENAME).write_text("{не json", encoding="utf-8")

    assert stability.load() == {}
    stability.record("A", True)
    assert stability.load()["A"].checks == 1


class _Check:
    def __init__(self, working: list[str], broken: list[str]):
        self.working = working
        self.broken = broken
        self.results = [
            *(ServiceResult(n, [CheckResult(n, True, "", target=n)]) for n in working),
            *(ServiceResult(n, [CheckResult(n, False, "", target=n)]) for n in broken),
        ]
        self.everything_works = bool(working) and not broken


ON = Status(core_present=True, winws_count=1, active_strategy="A")


@pytest.mark.parametrize(
    ("status", "check", "written"),
    [
        (ON, _Check(["YouTube"], []), True),
        (ON, _Check(["YouTube"], ["Discord"]), True),
        (ON, _Check([], ["YouTube", "Discord"]), False),
        (Status(core_present=True), _Check(["YouTube"], []), False),
        (
            Status(core_present=True, winws_count=1, active_strategy="A", active_vpn="VPN"),
            _Check(["YouTube"], []),
            False,
        ),
    ],
)
def test_only_meaningful_checks_are_written(home: Path, status, check, written: bool) -> None:
    (paths.core_utils() / "targets.txt").write_text("", encoding="utf-8")
    controller = Controller(Settings())
    controller.status = status

    controller._note_stability(check)

    assert ("A" in stability.load()) is written


# --- решения починки -----------------------------------------------------------


def test_shortlist_starts_with_favorites_and_skips_current(home: Path) -> None:
    names = ["a", "b", "c", "d", "e"]

    assert repair.shortlist(names, ["d", "a"], "a") == ["d", "b", "c"]


def test_shortlist_ignores_favorites_that_no_longer_exist(home: Path) -> None:
    assert "старая" not in repair.shortlist(["a", "b"], ["старая"], "")


def test_remaining_excludes_what_was_tried() -> None:
    assert repair.remaining(["a", "b", "c"], ["b"]) == ["a", "c"]


def _service(name: str, ok: bool) -> ServiceResult:
    return ServiceResult(service=name, checks=[CheckResult(name, ok, "")])


def _score(name: str, working: tuple, broken: tuple = (), **kwargs) -> StrategyScore:
    services = [*(_service(s, True) for s in working), *(_service(s, False) for s in broken)]
    return StrategyScore(name=name, ok=len(working), services=services, **kwargs)


def _report(*scores: StrategyScore, baseline=None, cancelled=False) -> Report:
    return Report(
        mode="services",
        started_at="",
        finished_at="",
        checked=[],
        scores=list(scores),
        baseline=baseline,
        cancelled=cancelled,
    )


def test_strategy_must_beat_the_baseline() -> None:
    baseline = _score("без", ("A",), ("B",), is_baseline=True)
    same = _score("x", ("A",), ("B",))

    assert repair.choose(_report(baseline, same, baseline=baseline)) is None


def test_better_strategy_is_chosen() -> None:
    baseline = _score("без", (), ("A", "B"), is_baseline=True)
    good = _score("x", ("A", "B"))

    chosen = repair.choose(_report(baseline, good, baseline=baseline))

    assert chosen is not None and chosen.name == "x"
    assert repair.fully_works(chosen)


def test_cancelled_run_chooses_nothing() -> None:
    good = _score("x", ("A",))

    assert repair.choose(_report(good, cancelled=True)) is None


def test_nothing_blocked_when_baseline_works() -> None:
    baseline = _score("без", ("A",), is_baseline=True)

    assert repair.nothing_is_blocked(_report(baseline, baseline=baseline))


def test_partial_strategy_is_not_full_success() -> None:
    assert not repair.fully_works(_score("x", ("A",), ("B",)))


# --- перенос настроек ----------------------------------------------------------

BAT = (
    '@echo off\nset "BIN={core}\\bin\\"\n'
    'start "x" /min "%BIN%winws.exe" --wf-tcp=443 --filter-tcp=443\n'
)


def _fill(home: Path) -> None:
    core = paths.core_dir()
    (core / "lists" / "list-general-user.txt").write_text("example.org\n", encoding="utf-8")
    (core / "lists" / "list-general.txt").write_text("штатный\n", encoding="utf-8")
    (core / "general (своя).bat").write_text(BAT.format(core=core), encoding="utf-8")
    (core / "general.bat").write_text(BAT.format(core=core), encoding="utf-8")
    appprofile.profiles_dir().mkdir(parents=True)
    (appprofile.profiles_dir() / "игра.json").write_text("{}", encoding="utf-8")


def test_export_takes_only_what_the_user_made(home: Path) -> None:
    _fill(home)
    target = home / "out.zip"

    backup.export(target, Settings(selected_strategy="general"))

    names = zipfile.ZipFile(target).namelist()
    assert "lists/list-general-user.txt" in names
    assert "strategies/general (своя).bat" in names
    assert "profiles/игра.json" in names
    assert "lists/list-general.txt" not in names
    assert "strategies/general.bat" not in names


def test_export_has_no_ai_settings_or_local_marks(home: Path) -> None:
    target = home / "out.zip"

    backup.export(target, Settings(first_run_done=True, theme="light"))

    data = json.loads(zipfile.ZipFile(target).read(backup.SETTINGS))
    assert data["theme"] == "light"
    assert "ai" not in data
    assert "first_run_done" not in data


def test_round_trip_restores_settings_and_files(home: Path) -> None:
    _fill(home)
    target = home / "out.zip"
    backup.export(target, Settings(theme="light"))
    (paths.core_lists() / "list-general-user.txt").unlink()

    settings = Settings(theme="dark", first_run_done=True)
    result = backup.restore(target, settings)

    assert settings.theme == "light"
    assert settings.first_run_done is True, "знакомство на этом компьютере уже пройдено"
    assert (paths.core_lists() / "list-general-user.txt").is_file()
    assert result.skipped == []


def test_strategy_paths_are_moved_to_the_new_place(home: Path, monkeypatch) -> None:
    _fill(home)
    target = home / "out.zip"
    backup.export(target, Settings())

    moved = home / "Другая папка" / "core"
    (moved / "lists").mkdir(parents=True)
    (moved / "utils").mkdir()
    monkeypatch.setattr(paths, "core_dir", lambda: moved)
    monkeypatch.setattr(paths, "core_lists", lambda: moved / "lists")
    monkeypatch.setattr(paths, "core_utils", lambda: moved / "utils")

    backup.restore(target, Settings())

    text = (moved / "general (своя).bat").read_text(encoding="utf-8")
    assert str(moved) in text


@pytest.mark.parametrize(
    "evil",
    [
        "../../evil.bat",
        "strategies/..\\..\\evil.bat",
        "strategies/general.bat",
        "lists/list-general.txt",
        "core/bin/winws.exe",
        "secrets.json",
        "utils/service.bat",
    ],
)
def test_archive_cannot_write_outside_or_replace_official_files(home: Path, evil: str) -> None:
    target = home / "evil.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(backup.MANIFEST, json.dumps({"format": backup.FORMAT}))
        archive.writestr(evil, "подмена")

    result = backup.restore(target, Settings())

    assert result.restored == []
    assert evil in result.skipped or evil.replace("\\", "/") in result.skipped
    assert not (home / "evil.bat").exists()
    assert not (paths.core_dir() / "general.bat").exists()


def test_foreign_zip_is_refused(home: Path) -> None:
    target = home / "other.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("readme.txt", "что-то своё")

    with pytest.raises(backup.BackupError):
        backup.restore(target, Settings())


def test_broken_file_is_refused(home: Path) -> None:
    target = home / "broken.zip"
    target.write_bytes(b"not a zip")

    with pytest.raises(backup.BackupError):
        backup.restore(target, Settings())


def test_unreadable_strategy_is_not_left_behind(home: Path) -> None:
    target = home / "bad.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(backup.MANIFEST, json.dumps({"format": backup.FORMAT}))
        archive.writestr("strategies/плохая (своя).bat", "@echo off\necho нет запуска\n")

    result = backup.restore(target, Settings())

    assert "strategies/плохая (своя).bat" in result.skipped
    assert not (paths.core_dir() / "плохая (своя).bat").exists()


# --- отчёт ----------------------------------------------------------------------


def test_report_has_findings_state_and_log() -> None:
    text = report.build_text(
        {
            "находки": [{"важность": "ошибка", "что": "Нет драйвера", "подробности": "удалён"}],
            "ядро": {"версия": "1.10.4"},
            "лог": ["строка журнала"],
        }
    )

    assert "Нет драйвера" in text
    assert "1.10.4" in text
    assert "строка журнала" in text


def test_report_says_when_nothing_was_found() -> None:
    assert "- ничего" in report.build_text({})


def test_issue_template_exists_and_asks_for_the_report() -> None:
    text = (Path(__file__).parents[1] / ".github" / "ISSUE_TEMPLATE" / "bug.yml").read_text(
        encoding="utf-8"
    )

    assert "Отчёт из программы" in text
