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
    controller._profile_declined = ""
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


def test_manually_stopped_profile_stays_off(bare: Controller) -> None:
    """Выключенный руками профиль не поднимается обратно сам.

    С галочкой «включать вместе с приложением» и запущенной игрой профиль
    возвращался через пару секунд после нажатия «Выключить» — кнопка
    выглядела неработающей, а в журнале копились сотни включений подряд.
    """
    bare._profile_declined = "roblox"

    bare._follow_apps("start", "roblox")

    assert bare.started == []


SECOND = Profile(
    name="obsidian",
    exe=r"C:\Apps\Obsidian.exe",
    tcp_ports=[443],
    addresses=["104.26.0.0/16"],
    auto_start=True,
)


def test_several_profiles_live_side_by_side(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включение второго профиля не должно гасить первый.

    Раньше контроллер держал одну пару «процесс и имя», и второй профиль
    молча занимал её место: человек включал профиль игры, потом профиль
    клиента — и обнаруживал, что игра снова лагает. К WinDivert при этом
    можно прицепить сколько угодно экземпляров winws.
    """
    controller = Controller.__new__(Controller)
    controller._profiles = {}

    alive = type("Fake", (), {"is_alive": lambda self: True})
    controller._profiles["roblox"] = alive()
    controller._profiles["obsidian"] = alive()

    assert controller._alive_profiles() == ("obsidian", "roblox")


def test_dead_profile_disappears_from_the_list() -> None:
    """Процесс мог умереть сам — список не должен обещать обратное."""
    controller = Controller.__new__(Controller)
    controller._profiles = {
        "roblox": type("Fake", (), {"is_alive": lambda self: False})(),
        "obsidian": type("Fake", (), {"is_alive": lambda self: True})(),
    }

    assert controller._alive_profiles() == ("obsidian",)
