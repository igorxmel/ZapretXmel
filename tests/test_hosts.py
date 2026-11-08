"""Файл hosts, который программа не может открыть.

Прав администратора бывает мало: hosts закрывает антивирус или с файла сняты
права. Раздел «Обновления» от этого падал при каждом открытии — у человека на
0.2.7 так было пять раз за вечер.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import hosts


@pytest.fixture
def hosts_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "hosts"
    path.write_text("127.0.0.1 localhost\n", encoding="utf-8")
    monkeypatch.setattr(hosts, "hosts_path", lambda: path)
    monkeypatch.setattr(hosts.paths, "backups_dir", lambda: tmp_path / "backups")
    monkeypatch.setattr(hosts, "flush_dns", lambda: None)
    return path


def _lock(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", refuse)
    monkeypatch.setattr(Path, "write_text", refuse)


def test_locked_file_does_not_break_status(hosts_file, monkeypatch) -> None:
    _lock(monkeypatch)

    state = hosts.status()

    assert not state.readable
    assert not state.managed


def test_locked_file_explains_itself_on_remove(hosts_file, monkeypatch) -> None:
    _lock(monkeypatch)

    with pytest.raises(hosts.HostsLocked, match="антивирус"):
        hosts.remove()


def test_locked_file_explains_itself_on_apply(hosts_file, monkeypatch) -> None:
    _lock(monkeypatch)

    with pytest.raises(hosts.HostsLocked):
        hosts.apply("0.0.0.0 example.com")


def test_section_round_trip(hosts_file) -> None:
    assert hosts.apply("1.2.3.4 a.example\n1.2.3.5 b.example") == 2

    state = hosts.status()
    assert state.readable and state.managed and state.managed_lines == 2

    assert hosts.remove()
    assert hosts_file.read_text(encoding="utf-8").strip() == "127.0.0.1 localhost"
