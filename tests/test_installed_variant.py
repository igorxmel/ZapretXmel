"""Установленный вариант: сборка папкой, обновление через установщик.

Переносная программа — один exe, и обновляется она подменой этого файла.
Установленная — две сотни файлов в Program Files, и подменять их на ходу
нельзя: она скачивает установщик новой версии и запускает его в тихом режиме.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.core import paths, singleton
from app.core.updater import github, selfupdate

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class _Release:
    version: str
    tag: str = "v9.9.9"
    assets: list = field(default_factory=list)


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Программа «установлена» в tmp_path; запуски процессов записываются."""
    monkeypatch.setattr(selfupdate, "_staged", "")
    monkeypatch.setattr(selfupdate, "_setup", None)
    monkeypatch.setattr(selfupdate, "_setup_started", False)
    monkeypatch.setattr(selfupdate, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "is_installed", lambda: True)
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(paths, "logs_dir", lambda: tmp_path / "data" / "logs")
    monkeypatch.setattr(selfupdate, "executable", lambda: tmp_path / "ZapretXmel.exe")

    def fetch(asset, target: Path, progress=None) -> str:
        target.write_bytes(b"x" * 4096)
        return "ab" * 32

    monkeypatch.setattr(github, "download", fetch)
    monkeypatch.setattr(selfupdate, "_published_hash", lambda release: "ab" * 32)

    launched: list[list[str]] = []
    monkeypatch.setattr(
        selfupdate.subprocess, "Popen", lambda command, **kwargs: launched.append(command)
    )
    return launched


def _release() -> _Release:
    return _Release(
        "9.9.9",
        assets=[
            github.Asset(selfupdate.ASSET_NAME, "", 1),
            github.Asset(selfupdate.SETUP_NAME, "", 1),
            github.Asset(selfupdate.SETUP_NAME + ".sha256", "", 1),
        ],
    )


def test_installed_program_takes_the_installer(installed) -> None:
    assert selfupdate.asset_name() == selfupdate.SETUP_NAME
    assert selfupdate.can_verify(_release())


def test_update_downloads_setup_and_leaves_program_files_alone(installed, tmp_path) -> None:
    selfupdate.update(_release())

    assert (tmp_path / "data" / "updates" / selfupdate.SETUP_NAME).is_file()
    assert not (tmp_path / "ZapretXmel.old.exe").exists()
    assert selfupdate.staged_version() == "9.9.9"
    assert "установится" in selfupdate.staged_note("9.9.9")
    assert installed == []


def test_restart_runs_setup_silently_and_asks_it_to_relaunch(installed) -> None:
    selfupdate.update(_release())

    selfupdate.restart([singleton.TRAY_FLAG, singleton.RESUME_PROXY_FLAG])

    command = installed[0]
    assert command[0].endswith(selfupdate.SETUP_NAME)
    assert {"/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LAUNCH=1"} <= set(command)
    assert f"/LAUNCHARGS={singleton.TRAY_FLAG} {singleton.RESUME_PROXY_FLAG}" in command


def test_closing_installs_without_relaunch_once(installed) -> None:
    selfupdate.update(_release())

    selfupdate.install_on_exit()
    selfupdate.install_on_exit()

    assert len(installed) == 1
    assert "/LAUNCH=1" not in installed[0]


def test_restart_already_started_setup_so_closing_does_not_repeat_it(installed) -> None:
    selfupdate.update(_release())
    selfupdate.restart([])
    selfupdate.install_on_exit()

    assert len(installed) == 1
    assert "/LAUNCH=1" in installed[0]


def test_nothing_downloaded_nothing_installed_on_exit(installed) -> None:
    selfupdate.install_on_exit()

    assert installed == []


def test_portable_program_never_runs_setup(installed, monkeypatch) -> None:
    monkeypatch.setattr(paths, "is_installed", lambda: False)

    selfupdate.install_on_exit()

    assert selfupdate.asset_name() == selfupdate.PORTABLE_NAME
    assert installed == []


def test_portable_takes_the_new_name_and_falls_back_to_the_old(monkeypatch) -> None:
    """Старые релизы несут переносную только как ZapretXmel.exe."""
    monkeypatch.setattr(paths, "is_installed", lambda: False)
    both = _release()
    both.assets.append(github.Asset(selfupdate.PORTABLE_NAME, "", 1))
    old = _Release("0.3.4", assets=[github.Asset(selfupdate.ASSET_NAME, "", 1)])

    assert selfupdate.asset_name(both) == selfupdate.PORTABLE_NAME
    assert selfupdate.asset_name(old) == selfupdate.ASSET_NAME


def test_release_names_carry_the_system() -> None:
    assert "Windows" in selfupdate.PORTABLE_NAME
    assert "Windows" in selfupdate.SETUP_NAME
    script = (ROOT / "installer" / "ZapretXmel.iss").read_text(encoding="utf-8-sig")
    assert f"OutputBaseFilename={Path(selfupdate.SETUP_NAME).stem}" in script


def test_leftover_setups_are_removed_at_start(installed, tmp_path) -> None:
    folder = tmp_path / "data" / "updates"
    folder.mkdir(parents=True)
    (folder / selfupdate.SETUP_NAME).write_bytes(b"old")

    selfupdate.cleanup()

    assert not any(folder.iterdir())


def test_onedir_build_is_recognised(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "ZapretXmel.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    paths.app_root.cache_clear()
    try:
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
        assert paths.is_installed()

        # Переносная распаковывается во временную папку, а не рядом с собой.
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path.parent / "_MEI12345"), raising=False)
        assert not paths.is_installed()
    finally:
        paths.app_root.cache_clear()


def test_installer_waits_for_the_same_mutex_the_program_holds() -> None:
    script = (ROOT / "installer" / "ZapretXmel.iss").read_text(encoding="utf-8-sig")

    assert singleton.MUTEX_NAME in script
    assert "--uninstall" in script


def test_uninstall_flag_cleans_up_without_a_window(monkeypatch) -> None:
    import app.__main__ as main
    from app.core import autostart, uninstall

    calls = []
    monkeypatch.setattr(
        autostart, "set_enabled", lambda wanted: calls.append(("autostart", wanted))
    )
    monkeypatch.setattr(uninstall, "remove_everything", lambda: calls.append("everything"))

    assert main.uninstall_for_setup() == 0
    assert calls == [("autostart", False), "everything"]
