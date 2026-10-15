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


def test_focus_does_not_fail_without_window() -> None:
    assert singleton.focus_existing("окна с таким заголовком нет") is False
