"""На какие сайты стратегия влияет. Свой сайт вне списков не должен считаться её провалом."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from app.core import coverage, ipset, lists, paths, repair, strategies
from app.core.batfile import Section
from app.core.config import Settings
from app.core.probe import services
from app.core.probe.services import CheckResult, ServiceResult
from app.ui.controller import Controller
from app.ui.views.autopick import AutoPickView

GENERAL = "list-general.txt"


def _by_list(path: Path) -> Section:
    return Section(["--filter-tcp=80,443", f"--hostlist={path}"])


def _by_ip(path: Path) -> Section:
    return Section(["--filter-tcp=80,443", f"--ipset={path}"])


@pytest.fixture
def listed(tmp_path: Path) -> Path:
    path = tmp_path / GENERAL
    path.write_text("known.example\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("host", "mode", "covered"),
    [
        ("known.example", "none", True),
        ("www.known.example", "none", True),
        ("my-site.example", "none", False),
        ("my-site.example", "any", True),
        ("my-site.example", "loaded", True),
    ],
)
def test_host_coverage(listed: Path, tmp_path: Path, host: str, mode: str, covered: bool) -> None:
    sections = [_by_list(listed), _by_ip(tmp_path / "ipset.txt")]

    assert coverage.host_is_covered(sections, host, mode) is covered


def test_other_ports_do_not_count(listed: Path) -> None:
    section = Section(["--filter-tcp=8443", f"--hostlist={listed}"])

    assert not coverage.host_is_covered([section], "known.example", "any")


def test_excluded_host_is_not_covered(listed: Path, tmp_path: Path) -> None:
    exclude = tmp_path / "exclude.txt"
    exclude.write_text("known.example\n", encoding="utf-8")
    section = Section(
        ["--filter-tcp=443", f"--hostlist={listed}", f"--hostlist-exclude={exclude}"]
    )

    assert not coverage.host_is_covered([section], "known.example", "none")


# --- решения --------------------------------------------------------------------


def _result(*checks: tuple[str, bool], name="Сервис", measures=True) -> ServiceResult:
    return ServiceResult(
        service=name,
        checks=[CheckResult(target, ok, "", target=target) for target, ok in checks],
        measures_bypass=measures,
    )


IGNORED = frozenset({"MySite"})


def test_uncovered_failure_is_not_the_strategys_fault() -> None:
    results = [_result(("YouTube", True), name="YouTube"), _result(("MySite", False), name="Мой")]

    assert repair.check_passes(results, IGNORED)
    assert not repair.check_passes(results)


def test_real_failure_still_counts() -> None:
    results = [_result(("YouTube", False), name="YouTube"), _result(("MySite", False), name="Мой")]

    assert not repair.check_passes(results, IGNORED)
    assert coverage.broken_services(results, IGNORED) == ["YouTube"]


def test_mixed_service_fails_only_for_covered_targets() -> None:
    assert repair.check_passes([_result(("Covered", True), ("MySite", False))], IGNORED)
    assert not repair.check_passes([_result(("Covered", False), ("MySite", True))], IGNORED)


def test_only_uncovered_passing_proves_nothing() -> None:
    """Открылся только сайт, на который стратегия не влияет: это не успех стратегии."""
    assert not repair.check_passes([_result(("MySite", True))], IGNORED)


def test_ping_only_service_is_not_judged() -> None:
    results = [_result(("YouTube", True)), _result(("DNS", False), measures=False)]

    assert repair.check_passes(results)


# --- настоящие фильтры и файл целей ---------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "bundle_1_10_3"


@pytest.fixture
def core(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import shutil

    root = tmp_path / "Program Files" / "core"
    shutil.copytree(FIXTURES, root)
    (root / "lists").mkdir(exist_ok=True)
    (root / "utils").mkdir(exist_ok=True)
    (root / "lists" / GENERAL).write_text("discord.com\n", encoding="utf-8")
    (root / "lists" / "ipset-all.txt").write_text(f"{ipset.NONE_MARKER}\n", encoding="utf-8")
    monkeypatch.setattr(paths, "core_dir", lambda: root)
    monkeypatch.setattr(paths, "core_lists", lambda: root / "lists")
    monkeypatch.setattr(paths, "core_utils", lambda: root / "utils")
    return root


def _own_targets(text: str) -> None:
    services.user_targets_file().write_text(text, encoding="utf-8")


def test_own_site_outside_lists_is_found(core: Path) -> None:
    _own_targets('### Мои\nA = "https://www.my-site.example"\nB = "https://discord.com"\n')

    assert coverage.own_uncovered_hosts() == ["www.my-site.example"]
    assert "A" in coverage.uncovered_target_names()
    assert "B" not in coverage.uncovered_target_names()


def test_ping_targets_are_not_reported(core: Path) -> None:
    _own_targets('### Мои\nP = "PING:9.9.9.9"\n')

    assert coverage.own_uncovered_hosts() == []


def test_adding_to_own_list_makes_the_site_covered(core: Path) -> None:
    _own_targets('### Мои\nA = "https://www.my-site.example"\n')
    assert strategies.discover(core)

    added = coverage.add_to_own_list(["www.my-site.example"])

    assert added == 1
    assert coverage.own_uncovered_hosts() == []
    own = next(x for x in lists.USER_LISTS if x.filename == "list-general-user.txt")
    assert lists.read(own).entries == ["my-site.example"], "заглушка больше не нужна"


def test_adding_twice_does_not_duplicate(core: Path) -> None:
    coverage.add_to_own_list(["my-site.example"])

    assert coverage.add_to_own_list(["my-site.example"]) == 0


def test_template_explains_lists(core: Path) -> None:
    services.ensure_user_targets()

    assert "Списки" in services.user_targets_file().read_text(encoding="utf-8")


# --- экран подбора ------------------------------------------------------------------


@pytest.fixture(scope="module")
def app() -> QApplication:
    # Ссылку надо держать: удалённый сборщиком QApplication роняет Qt целиком.
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app: QApplication, core: Path, monkeypatch: pytest.MonkeyPatch) -> AutoPickView:
    monkeypatch.setattr(Settings, "save", lambda _self: None)
    return AutoPickView(Controller(Settings()))


def test_warning_appears_and_the_button_fixes_it(view: AutoPickView) -> None:
    _own_targets('### Мои\nA = "https://my-site.example"\n')

    view.reload()
    assert not view._coverage_box.isHidden()
    assert "my-site.example" in view._coverage_note.text()

    view._coverage_button.click()

    assert view._coverage_box.isHidden()
    assert coverage.own_uncovered_hosts() == []


def test_no_warning_without_problem_sites(view: AutoPickView) -> None:
    _own_targets('### Мои\nA = "https://discord.com"\n')

    view.reload()

    assert view._coverage_box.isHidden()
