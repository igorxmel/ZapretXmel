"""Список программ для записи профиля: одна строка на программу, а не на процесс."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import appprofile
from app.core.appprofile import AppInfo


def test_processes_of_one_program_become_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Семь «Discord.exe (pid …)» подряд — и непонятно было, какой выбирать."""
    discord = r"C:\Users\me\AppData\Local\Discord\app-1.0\Discord.exe"
    monkeypatch.setattr(
        appprofile,
        "running_apps",
        lambda: [
            AppInfo(11, "Discord.exe", discord),
            AppInfo(12, "Discord.exe", discord),
            AppInfo(13, "Discord.exe", discord),
            AppInfo(20, "steam.exe", r"C:\Games\Steam\steam.exe"),
        ],
    )
    monkeypatch.setattr(appprofile, "display_name", lambda exe: exe.rsplit("\\", 1)[-1][:-4])

    programs = appprofile.running_programs()

    assert [(p.title, p.pids) for p in programs] == [("Discord", (11, 12, 13)), ("steam", (20,))]


def test_system_and_own_processes_are_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setattr(
        appprofile,
        "running_apps",
        lambda: [
            AppInfo(1, "svchost.exe", r"C:\Windows\System32\svchost.exe"),
            AppInfo(2, "winws.exe", r"D:\zapret\bin\winws.exe"),
            AppInfo(3, "ZapretXmel.exe", r"D:\ZapretXmel\ZapretXmel.exe"),
            AppInfo(4, "game.exe", r"D:\Games\game.exe"),
            AppInfo(5, "noexe", ""),
        ],
    )

    assert [p.file_name for p in appprofile.running_programs()] == ["game.exe"]


def test_recording_follows_every_process_of_the_program(monkeypatch) -> None:
    """Сеть у браузеров и клиентов на Electron держит не главный процесс, а соседний."""
    monkeypatch.setattr(appprofile, "process_tree", lambda pid: {pid})
    monkeypatch.setattr(appprofile, "pids_of", lambda exe: {11, 12, 99})
    connections = [
        SimpleNamespace(pid=12, raddr=("8.8.4.4", 443), type=appprofile.socket.SOCK_STREAM),
        SimpleNamespace(pid=99, raddr=("1.1.1.1", 50000), type=appprofile.socket.SOCK_DGRAM),
        SimpleNamespace(pid=77, raddr=("9.9.9.9", 443), type=appprofile.socket.SOCK_STREAM),
    ]
    monkeypatch.setattr(appprofile.psutil, "net_connections", lambda kind: connections)

    recorder = appprofile.Recorder([11, 12], exe=r"C:\app\app.exe")
    recorder.refresh_tree()
    recorder.sample()

    assert set(recorder.seen) == {("8.8.4.4", 443, "tcp"), ("1.1.1.1", 50000, "udp")}


def test_single_pid_still_works(monkeypatch) -> None:
    monkeypatch.setattr(appprofile, "process_tree", lambda pid: {pid, pid + 1})

    recorder = appprofile.Recorder(5)

    assert recorder.pid == 5 and recorder._pids == {5, 6}
