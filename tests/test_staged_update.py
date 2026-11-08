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


def test_newer_release_goes_over_the_staged_one(program) -> None:
    selfupdate.update(_Release("0.3.1"))

    # Отодвинутый файл — это работающая программа: Windows не даёт его удалить.
    with _old(program).open("rb"):
        selfupdate.update(_Release("0.3.2"))

    assert program.read_text(encoding="utf-8") == "0.3.2"
    assert _old(program).read_text(encoding="utf-8") == "0.3.0"
    assert selfupdate.staged_version() == "0.3.2"


def test_busy_leftover_explains_itself_and_keeps_program(program) -> None:
    _old(program).write_text("старое", encoding="utf-8")

    with _old(program).open("rb"), pytest.raises(selfupdate.SelfUpdateError, match="занят"):
        selfupdate.update(_Release("0.3.1"))

    assert program.read_text(encoding="utf-8") == "0.3.0"
    assert selfupdate.staged_version() == ""
