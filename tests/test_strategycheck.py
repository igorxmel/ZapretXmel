"""Проверка стратегий без запуска: winws --wf-save разбирает аргументы и выходит.

Поводом стала «general (FAKE TLS AUTO)»: из-за `^!`, переданного дословно, winws
не находил файла и выходил, а программа месяцами показывала её как обычную.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import strategycheck


def _spec(name: str, *argv: str):
    return SimpleNamespace(name=name, argv=list(argv))


@pytest.fixture
def winws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Подставной winws: падает на аргументе «^!», как настоящий, остальное сохраняет."""
    exe = tmp_path / "core" / "bin" / "winws.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"winws")
    runs: list[list[str]] = []

    def run(command, **kwargs):
        runs.append(command)
        argv = command[1:]
        if any(arg.endswith("=^!") for arg in argv):
            return SimpleNamespace(
                returncode=1,
                stdout="github version v72.9 (abc)\n\ncould not read ^!\n",
                stderr="",
            )
        saved = next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--wf-save="))
        Path(saved).write_text("tcp", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(strategycheck.subprocess, "run", run)
    monkeypatch.setattr(strategycheck.paths, "winws_exe", lambda: exe)
    monkeypatch.setattr(strategycheck.paths, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(strategycheck.elevation, "is_admin", lambda: True)
    monkeypatch.setattr(strategycheck.lists, "ensure_user_lists", lambda: None)
    return {"exe": exe, "runs": runs}


def test_broken_strategy_is_reported_in_winws_words(winws) -> None:
    reason = strategycheck.check(_spec("x", "--dpi-desync-fake-tls=^!"))

    assert reason == "could not read ^!"


def test_good_strategy_passes(winws) -> None:
    assert strategycheck.check(_spec("x", "--dpi-desync=fake")) == ""


def test_results_are_cached_until_arguments_change(winws) -> None:
    good, bad = _spec("good", "--a=1"), _spec("bad", "--b=^!")

    assert strategycheck.check_all([good, bad]) == {"bad": "could not read ^!"}
    assert len(winws["runs"]) == 2

    strategycheck.check_all([good, bad])
    assert len(winws["runs"]) == 2, "неизменные стратегии проверялись заново"

    fixed = _spec("bad", "--b=!")
    assert strategycheck.check_all([good, fixed]) == {}
    assert len(winws["runs"]) == 3
    assert strategycheck.known_broken() == {}


def test_new_core_version_rechecks_everything(winws) -> None:
    spec = _spec("good", "--a=1")
    strategycheck.check_all([spec])
    winws["exe"].write_bytes(b"winws, but newer")

    strategycheck.check_all([spec])

    assert len(winws["runs"]) == 2


def test_without_admin_nothing_is_marked_broken(winws, monkeypatch) -> None:
    """winws без прав не запустится вовсе — и любая стратегия выглядела бы сломанной."""
    monkeypatch.setattr(strategycheck.elevation, "is_admin", lambda: False)

    assert strategycheck.check_all([_spec("bad", "--b=^!")]) == {}
    assert winws["runs"] == []


def test_hung_winws_is_a_reason_not_a_crash(winws, monkeypatch) -> None:
    def hang(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("winws", 15)

    monkeypatch.setattr(strategycheck.subprocess, "run", hang)

    assert "не ответил" in strategycheck.check(_spec("x"))


def test_real_bundle_strategies_parse_into_checkable_arguments() -> None:
    """После исправления разбора `^` ни одна стратегия сборки не несёт «^!»."""
    from app.core.batfile import parse_bat

    bundle = Path(__file__).parent / "fixtures" / "bundle_1_10_3"
    spec = parse_bat(bundle / "general (FAKE TLS AUTO).bat")

    assert not any(arg.endswith("=^!") for arg in spec.argv)
