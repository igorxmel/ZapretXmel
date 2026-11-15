"""Обновление, которое уже поставлено, но ещё не запущено.

Автообновление поставило 0.3.1 и ждало перезапуска: окно было открыто. Раздел
«Обновления» об этом не знал и предлагал 0.3.1 снова, а вторая установка
пыталась удалить `ZapretXmel.old.exe` — работающую программу — и трижды падала
с «Отказано в доступе».
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.core.updater import selfupdate


@dataclass
class _Release:
    version: str
    assets: list = field(default_factory=list)


@pytest.fixture
def program(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    exe = tmp_path / "ZapretXmel.exe"
    exe.write_text("0.3.0", encoding="utf-8")
    monkeypatch.setattr(selfupdate, "_staged", "")
    monkeypatch.setattr(selfupdate, "_pending", None)
    monkeypatch.setattr(selfupdate, "_relaunch", None)
    monkeypatch.setattr(selfupdate, "_finished", False)
    monkeypatch.setattr(selfupdate.paths, "is_installed", lambda: False)
    monkeypatch.setattr(selfupdate, "is_frozen", lambda: True)
    monkeypatch.setattr(selfupdate, "executable", lambda: exe)
    monkeypatch.setattr(selfupdate, "current_version", lambda: "0.3.0")

    def download(release, progress=None, on_bytes=None) -> Path:
        new = exe.with_suffix(".new.exe")
        new.write_text(release.version, encoding="utf-8")
        return new

    monkeypatch.setattr(selfupdate, "download", download)
    return exe


def _old(exe: Path) -> Path:
    return exe.with_suffix(".old.exe")


def test_installed_version_is_not_offered_again(program, monkeypatch) -> None:
    selfupdate.update(_Release("0.3.1"))
    monkeypatch.setattr(selfupdate.github, "latest_release", lambda *a, **k: _Release("0.3.1"))

    assert selfupdate.staged_version() == "0.3.1"
    assert selfupdate.check() is None


def test_running_program_file_is_left_alone_until_exit(program) -> None:
    """Переносная достаёт модули из своего exe по имени. Подмена на ходу роняла её.

    0.4.3 поставила 0.4.4 на место своего файла и через десять минут, на первом же
    новом импорте, упала с «zlib.error: incorrect header check».
    """
    selfupdate.update(_Release("0.3.1"))

    assert program.read_text(encoding="utf-8") == "0.3.0"
    assert not _old(program).exists()

    selfupdate.install_on_exit()

    assert program.read_text(encoding="utf-8") == "0.3.1"
    assert _old(program).read_text(encoding="utf-8") == "0.3.0"


def test_newer_release_replaces_the_pending_one(program) -> None:
    selfupdate.update(_Release("0.3.1"))
    selfupdate.update(_Release("0.3.2"))

    assert program.read_text(encoding="utf-8") == "0.3.0"
    assert selfupdate.staged_version() == "0.3.2"

    selfupdate.install_on_exit()
    assert program.read_text(encoding="utf-8") == "0.3.2"


def test_restart_waits_for_the_swap_then_launches(program, monkeypatch) -> None:
    launched = []
    monkeypatch.setattr(selfupdate.subprocess, "Popen", lambda args, **_: launched.append(args))
    selfupdate.update(_Release("0.3.1"))

    selfupdate.restart(["--tray"])
    assert launched == []

    selfupdate.install_on_exit()
    selfupdate.install_on_exit()

    assert program.read_text(encoding="utf-8") == "0.3.1"
    assert len(launched) == 1 and "--tray" in launched[0]


def test_busy_leftover_keeps_the_program_working(program) -> None:
    _old(program).write_text("старое", encoding="utf-8")
    selfupdate.update(_Release("0.3.1"))

    with _old(program).open("rb"):
        selfupdate.install_on_exit()

    assert program.read_text(encoding="utf-8") == "0.3.0"


def test_undelivered_update_is_dropped_at_start(program) -> None:
    """Программу убили, не дав выйти: ставить при запуске поздно — exe уже работает."""
    stale = program.with_suffix(".new.exe")
    stale.write_text("0.3.1", encoding="utf-8")

    selfupdate.cleanup()

    assert not stale.exists()
    assert program.read_text(encoding="utf-8") == "0.3.0"
