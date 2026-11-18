"""Режим проверки собранной программы: флаги, итог строкой, куда кладётся «обновление»."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app import __version__, smoke
from app.core import paths, singleton


@pytest.fixture
def logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "data")
    return tmp_path


def test_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["ZapretXmel.exe"])
    assert not smoke.requested()

    monkeypatch.setattr(sys, "argv", ["ZapretXmel.exe", "--smoke"])
    assert smoke.requested()
    assert smoke.update_source() is None

    target = tmp_path / "new.exe"
    monkeypatch.setattr(sys, "argv", ["ZapretXmel.exe", f"--smoke-update={target}"])
    assert smoke.requested()
    assert smoke.update_source() == target.resolve()


def test_each_run_appends_a_line(logs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Перезапущенный после обновления экземпляр дописывает свою строку к первой."""
    monkeypatch.setattr(sys, "argv", ["ZapretXmel.exe", "--smoke"])
    smoke.report(True, "update=ZapretXmel.new.exe")
    monkeypatch.setattr(sys, "argv", ["ZapretXmel.exe", singleton.RESTART_FLAG, "--smoke"])
    smoke.report(False, "раздел lists не открылся")

    lines = smoke.result_file().read_text(encoding="utf-8").splitlines()
    assert lines == [
        f"ok {__version__} restarted=False update=ZapretXmel.new.exe",
        f"fail {__version__} restarted=True раздел lists не открылся",
    ]


def test_portable_update_lands_next_to_the_exe(
    logs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Туда же, куда его скачало бы настоящее обновление, — иначе проверка не про то."""
    from app.core.updater import selfupdate

    exe = logs / "app" / "ZapretXmel.exe"
    exe.parent.mkdir()
    source = logs / "built.exe"
    source.write_bytes(b"MZ new")
    monkeypatch.setattr(paths, "is_installed", lambda: False)
    monkeypatch.setattr(selfupdate, "executable", lambda: exe)

    staged = smoke._stage(source)

    assert staged == exe.with_name("ZapretXmel.new.exe")
    assert staged.read_bytes() == b"MZ new"


def test_installed_update_goes_to_the_updates_folder(
    logs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = logs / "setup.exe"
    source.write_bytes(b"MZ setup")
    monkeypatch.setattr(paths, "is_installed", lambda: True)

    staged = smoke._stage(source)

    assert staged == logs / "data" / "updates" / "ZapretXmel-Windows-Setup.exe"
