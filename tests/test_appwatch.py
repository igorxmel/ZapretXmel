"""Тесты профиля, который поднимается вместе с приложением.

Профиль — это отдельный экземпляр winws, поэтому важнее всего, когда
программа **не** вмешивается: выключенный автозапуск и профиль, поднятый
руками, трогать нельзя.
"""

from __future__ import annotations

from app.core import appwatch

GAME = r"D:\Games\Shooter\game.exe"
RUNNING = {GAME.lower(), r"c:\windows\explorer.exe"}


def test_running_app_is_found_by_path() -> None:
    assert appwatch.is_running(GAME, RUNNING)


def test_path_is_compared_without_case() -> None:
    assert appwatch.is_running(GAME.upper(), RUNNING)


def test_moved_application_is_still_recognised() -> None:
    """Игру перенесли или обновил лаунчер — путь другой, программа та же."""
    assert appwatch.is_running(r"E:\Games\Shooter\game.exe", RUNNING)


def test_other_programs_are_not_ours() -> None:
    assert not appwatch.is_running(r"D:\Games\Other\other.exe", RUNNING)


def test_empty_executable_is_never_running() -> None:
    assert not appwatch.is_running("", RUNNING)


def test_profile_starts_when_the_app_appears() -> None:
    assert appwatch.decide(GAME, auto=True, profile_active=False, running=RUNNING) == "start"


def test_profile_stops_when_the_app_is_gone() -> None:
    assert appwatch.decide(GAME, auto=True, profile_active=True, running=set()) == "stop"


def test_nothing_happens_while_the_app_runs() -> None:
    assert appwatch.decide(GAME, auto=True, profile_active=True, running=RUNNING) == ""


def test_disabled_autostart_is_left_alone() -> None:
    """Профиль, поднятый руками, программа гасить не должна."""
    assert appwatch.decide(GAME, auto=False, profile_active=True, running=set()) == ""
    assert appwatch.decide(GAME, auto=False, profile_active=False, running=RUNNING) == ""


def test_profile_without_executable_is_skipped() -> None:
    assert appwatch.decide("", auto=True, profile_active=False, running=RUNNING) == ""


def test_start_and_stop_do_not_chase_each_other() -> None:
    """Решение не должно просить поднять профиль, пока он уже поднимается.

    На этом программа падала насмерть: `start_profile` начинался со
    `stop_profile`, тот звал обновление состояния, обновление снова
    спрашивало «не пора ли поднять профиль» — профиль ведь ещё не поднят, —
    и всё повторялось до RecursionError. Перезапуск не спасал: галочка
    автозапуска лежит в самом профиле, и цикл начинался заново.

    Здесь проверяется сама развилка: пока профиль считается активным,
    команды «start» быть не может, а значит и повторного входа.
    """
    running = {r"c:\games\game.exe"}

    assert appwatch.decide(r"C:\Games\game.exe", True, False, running) == "start"
    assert appwatch.decide(r"C:\Games\game.exe", True, True, running) == ""
