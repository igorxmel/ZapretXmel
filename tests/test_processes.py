"""Дешёвый перебор процессов и независимость прокси от программы."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psutil

from app.core import appwatch, processes, telegram
from app.core.process import ManagedProcess


def test_snapshot_sees_this_process() -> None:
    me = psutil.Process().name()

    assert os.getpid() in processes.pids_named(me.upper())


def test_snapshot_matches_psutil() -> None:
    """Снимок обязан видеть те же процессы, что и psutil, — иначе опрос врёт."""
    ours = {pid for pid, _ in processes.all_names()}
    theirs = set(psutil.pids())

    # Процессы рождаются и умирают между двумя вызовами — допускаем расхождение.
    assert len(ours ^ theirs) < max(10, len(theirs) // 20)


def test_executable_of_vanished_process_is_empty() -> None:
    assert processes.executable(0x7FFFFFF0) == ""


def test_app_profiles_resolve_only_matching_names(monkeypatch) -> None:
    asked: list[int] = []
    monkeypatch.setattr(
        processes, "all_names", lambda: [(1, "Game.exe"), (2, "chrome.exe"), (3, "game.exe")]
    )
    monkeypatch.setattr(
        processes,
        "executable",
        lambda pid: asked.append(pid) or {1: r"D:\A\Game.exe", 3: r"E:\B\game.exe"}[pid],
    )

    found = appwatch.running_executables([r"C:\Games\GAME.EXE"])

    assert found == {r"d:\a\game.exe", r"e:\b\game.exe"}
    assert sorted(asked) == [1, 3], "путь у чужих процессов спрашивать незачем"


def test_uncaptured_child_does_not_wait_for_us(tmp_path: Path) -> None:
    """Прокси не должен замирать, если программа перестала читать его вывод.

    Ребёнок пишет мегабайт — с перехватом это переполнило бы канал, пока
    никто не читает. Без перехвата он обязан закончить сам.
    """
    child = ManagedProcess(capture=False)
    child.start([sys.executable, "-c", "import sys; sys.stdout.write('x' * 1_048_576)"])
    try:
        process = child._process
        assert process is not None
        assert process.wait(timeout=20) == 0
    finally:
        child.stop()


def test_telegram_proxy_output_is_not_captured() -> None:
    assert telegram.TelegramProxy()._process._capture is False


def test_full_system_snapshot_runs_end_to_end() -> None:
    """Сломанный импорт внутри сбора сведений не ловил ни один тест по частям."""
    from app.core.diagnostics import collectors

    facts = collectors.collect()

    assert isinstance(facts.conflicting_processes, list)
    assert isinstance(facts.winws_cmdlines, list)


def test_conflicting_process_is_found_by_name(monkeypatch) -> None:
    from app.core.diagnostics import collectors

    name, label = next(iter(collectors.CONFLICTING_PROCESSES.items()))
    monkeypatch.setattr(processes, "all_names", lambda: [(1, name.upper()), (2, "chrome.exe")])

    assert collectors.find_conflicting_processes() == [label]


def test_winws_instance_details_are_read_only_for_matching_names(monkeypatch) -> None:
    """Подробности всех процессов подряд занимали больше минуты."""
    from app.core import winws

    asked: list[int] = []

    class Fake:
        def __init__(self, pid):
            asked.append(pid)

        def exe(self):
            return "C:\\core\\bin\\winws.exe"

        def cmdline(self):
            return ["winws.exe", "--wf-tcp=443"]

    monkeypatch.setattr(processes, "all_names", lambda: [(7, "winws.exe"), (8, "chrome.exe")])
    monkeypatch.setattr(winws.psutil, "Process", Fake)

    found = winws.find_instances()

    assert [item.pid for item in found] == [7]
    assert asked == [7]
    assert found[0].cmdline == ["winws.exe", "--wf-tcp=443"]
