"""Тесты защиты от второго запуска.

Проверяется сама механика мьютекса: первый вызов занимает имя, второй по тому
же имени его видит. Для этого имя подменяется на уникальное — иначе тест
столкнулся бы с настоящей запущенной программой.
"""

from __future__ import annotations

import ctypes
import uuid
from ctypes import wintypes

import pytest

from app.core import singleton


@pytest.fixture
def unique_name(monkeypatch: pytest.MonkeyPatch) -> str:
    name = f"Local\\ZapretXmel.Test.{uuid.uuid4().hex}"
    monkeypatch.setattr(singleton, "MUTEX_NAME", name)
    monkeypatch.setattr(singleton, "_handle", None)
    # И событие тоже: с настоящим именем тест подал бы сигнал живой программе,
    # если она у человека в этот момент запущена, и поднял бы её окно.
    monkeypatch.setattr(singleton, "ACTIVATE_EVENT_NAME", f"{name}.Activate")
    monkeypatch.setattr(singleton, "_event", None)
    return name


def test_first_launch_succeeds(unique_name: str) -> None:
    assert singleton.acquire()


def test_second_launch_is_detected(unique_name: str) -> None:
    """Пока имя занято чужим процессом, повторный запуск должен это видеть."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    holder = kernel32.CreateMutexW(None, True, unique_name)

    try:
        assert not singleton.acquire()
    finally:
        kernel32.CloseHandle(holder)


def test_retry_after_the_holder_is_gone_succeeds(unique_name: str) -> None:
    """После снятия зависшего экземпляра повторная попытка обязана пройти.

    Свой дескриптор от неудачной попытки держит объект ядра живым — если его
    не закрыть, имя так и останется занятым нами самими.
    """
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    holder = kernel32.CreateMutexW(None, True, unique_name)

    assert not singleton.acquire()
    kernel32.CloseHandle(holder)

    assert singleton.acquire()


def test_sources_run_reports_no_other_instances() -> None:
    """В исходниках программа живёт внутри pythonw — чужие процессы не трогаем."""
    assert singleton.other_instances() == []


def test_name_is_scoped_to_session() -> None:
    """Префикс Local\\ даёт каждому пользователю свою копию на сервере терминалов."""
    assert singleton.MUTEX_NAME.startswith("Local\\")


def test_handle_is_kept_alive(unique_name: str) -> None:
    """Если дать сборщику мусора закрыть мьютекс, защита исчезнет на ходу."""
    singleton.acquire()

    assert singleton._handle, "дескриптор должен остаться в модуле"


def test_focus_does_not_fail_without_window(unique_name: str) -> None:
    assert singleton.focus_existing("окна с таким заголовком нет") is False


# --- повторный запуск при окне в трее ---------------------------------------


def test_activation_event_roundtrip(unique_name: str) -> None:
    """Второй запуск подаёт сигнал, первый его получает — и ровно один раз."""
    assert singleton.acquire()

    assert singleton.signal_existing()
    assert singleton.wait_activation(500) is True
    assert singleton.wait_activation(50) is False, "автосброс: один сигнал — один показ"


def test_signal_without_a_listener_reports_failure(unique_name: str) -> None:
    """Экземпляр прошлой версии события не создаёт: подавать сигнал некому."""
    assert singleton.signal_existing() is False


def test_signal_sent_early_is_not_lost(unique_name: str) -> None:
    """Слушатель стартует позже мьютекса, и сигнал в промежутке не должен пропасть."""
    singleton.acquire()
    singleton.signal_existing()

    assert singleton.wait_activation(500) is True


def test_focus_uses_the_event_and_leaves_the_window_to_its_owner(
    unique_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import foreground

    def forbidden(*args, **kwargs):
        raise AssertionError("окно показали снаружи, в обход Qt")

    singleton.acquire()
    monkeypatch.setattr(foreground, "force", forbidden)

    assert singleton.focus_existing() is True


def test_refused_foreground_is_not_taken_for_a_hung_instance(
    unique_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows отказывает в переносе окна вперёд постоянно: это не зависание.

    Раньше отказ принимали за «окна нет» и предлагали завершить процесс.
    """
    from app.core import foreground

    monkeypatch.setattr(foreground, "find", lambda title: 777)
    monkeypatch.setattr(foreground, "is_visible", lambda hwnd: True)
    monkeypatch.setattr(foreground, "force", lambda hwnd: False)

    assert singleton.focus_existing() is True


def test_hidden_window_is_never_shown_from_outside(
    unique_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Спрятанное в трей окно так показывать нельзя: оно не отвечает на нажатия."""
    from app.core import foreground

    def forbidden(*args, **kwargs):
        raise AssertionError("скрытое окно показано в обход Qt")

    monkeypatch.setattr(foreground, "find", lambda title: 777)
    monkeypatch.setattr(foreground, "is_visible", lambda hwnd: False)
    monkeypatch.setattr(foreground, "force", forbidden)

    assert singleton.focus_existing() is False


def test_restart_flag_is_passed_by_both_restarts(monkeypatch, tmp_path) -> None:
    """После обновления прежний экземпляр ещё держит окно и мьютекс.

    Без признака новый принимал его за живой, просил показаться и выходил —
    а прежний тут же закрывался, и не оставалось ни одного экземпляра.
    """
    from app.core import location
    from app.core.updater import selfupdate

    launched: list[list[str]] = []
    monkeypatch.setattr("subprocess.Popen", lambda args, **_: launched.append(args))
    monkeypatch.setattr(selfupdate, "executable", lambda: tmp_path / "Z.exe")

    selfupdate.restart()
    location.restart(tmp_path / "Z.exe")

    assert all(singleton.RESTART_FLAG in args for args in launched) and len(launched) == 2
