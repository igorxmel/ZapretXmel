"""Тесты контроллера — той его части, что обходится без окна.

Контроллер живёт в слое интерфейса и вообще-то требует Qt, но проверяемое
здесь решение к Qt не относится: это защита от повторного входа, на которой
программа падала насмерть.
"""

from __future__ import annotations

import pytest

from app.core import appprofile
from app.core.appprofile import Profile
from app.ui.controller import Controller

PROFILE = Profile(
    name="roblox",
    exe=r"C:\Games\RobloxPlayerBeta.exe",
    tcp_ports=[443],
    addresses=["128.116.0.0/16"],
    auto_start=True,
)


@pytest.fixture
def bare(monkeypatch: pytest.MonkeyPatch) -> Controller:
    """Контроллер без инициализации Qt.

    Нужен ровно один метод и два поля; поднимать ради этого QApplication и
    опрос системы незачем. Запуск профиля подменён на запись в список —
    проверяется именно то, дойдёт ли до него дело.
    """
    controller = Controller.__new__(Controller)
    controller._profile_busy = False
    controller._profile_failed = ""
    controller.started = []

    monkeypatch.setattr(appprofile, "load_all", lambda: [PROFILE])
    monkeypatch.setattr(
        Controller, "start_profile", lambda self, profile: self.started.append(profile.name)
    )
    return controller


def test_profile_is_started_when_nothing_mesh(bare: Controller) -> None:
    """Обычный случай: приложение запустилось, профиль поднимается."""
    bare._follow_apps("start", "roblox")

    assert bare.started == ["roblox"]


def test_busy_controller_does_not_start_a_second_time(bare: Controller) -> None:
    """Пока профиль поднимается, просить поднять его снова нельзя.

    `start_profile` начинается со `stop_profile`, тот обновляет состояние,
    обновление публикует его и снова спрашивает «не пора ли поднять
    профиль» — профиль ведь ещё не поднят. Без этой защиты выходила
    бесконечная рекурсия и RecursionError, причём перезапуск не помогал:
    галочка автозапуска хранится в самом профиле, и всё начиналось заново.
    """
    bare._profile_busy = True

    bare._follow_apps("start", "roblox")

    assert bare.started == [], "повторный вход — это и есть та самая рекурсия"


def test_failed_profile_is_not_retried_forever(bare: Controller) -> None:
    """Неудачный запуск не повторяется, пока приложение не перезапустят.

    Иначе каждая проверка состояния снова лезет поднимать winws: в журнале
    одна и та же строка повторилась две с половиной тысячи раз.
    """
    bare._profile_failed = "roblox"

    bare._follow_apps("start", "roblox")

    assert bare.started == []
