"""Очистка кеша Discord: удаляется только кеш, вход и настройки остаются."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import discordcache


@pytest.fixture
def roaming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(discordcache, "roaming", lambda: tmp_path)
    monkeypatch.setattr(discordcache, "running", lambda: [])
    return tmp_path


def _fill(folder: Path, size: int = 2048) -> None:
    folder.mkdir(parents=True)
    (folder / "data_0").write_bytes(b"x" * size)


def test_only_cache_folders_are_removed(roaming: Path) -> None:
    for name in discordcache.CACHE_FOLDERS:
        _fill(roaming / "discord" / name)
    _fill(roaming / "discordptb" / "GPUCache")
    keep = roaming / "discord" / "Local Storage"
    _fill(keep)
    (roaming / "discord" / "settings.json").write_text("{}", encoding="utf-8")

    outcome = discordcache.clear()

    assert outcome.level == "ok" and outcome.verdict == "очищен"
    assert discordcache.cache_dirs() == []
    assert keep.is_dir(), "вход хранится рядом и трогать его нельзя"
    assert (roaming / "discord" / "settings.json").is_file()


def test_nothing_to_clear_is_not_an_error(roaming: Path) -> None:
    outcome = discordcache.clear()

    assert outcome.level == "ok"
    assert "нечего" in outcome.verdict


def test_running_discord_is_closed_first(roaming: Path, monkeypatch) -> None:
    _fill(roaming / "discord" / "Cache")
    closed = []
    monkeypatch.setattr(discordcache, "running", lambda: ["discord"])
    monkeypatch.setattr(discordcache, "_close", lambda processes: closed.append(processes))
    monkeypatch.setattr(discordcache.time, "sleep", lambda _s: None)

    outcome = discordcache.clear()

    assert closed == [["discord"]]
    assert "закрыт" in outcome.detail
