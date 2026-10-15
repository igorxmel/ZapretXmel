"""Тесты сторожа.

Сторож может сам переключить стратегию, поэтому проверяется в первую
очередь, когда он молчит: выключенный обход, включённый VPN и исправные
сервисы поводом для тревоги не являются.
"""

from __future__ import annotations

from app.core import watch


def decide(**changes):
    """Решение при исправном обходе и сломанном Discord, если не сказано иначе."""
    arguments = {
        "broken": ["Discord"],
        "active": True,
        "vpn": False,
        "autoswitch": False,
        "favorites": [],
        "current": "general (ALT)",
        "tried": [],
    }
    arguments.update(changes)
    broken = arguments.pop("broken")
    return watch.decide(broken, **arguments)


def test_working_services_are_not_news() -> None:
    assert decide(broken=[]).quiet


def test_vpn_silences_the_watchdog() -> None:
    """Через туннель открывается всё подряд — проверка измеряет VPN."""
    decision = decide(vpn=True)

    assert decision.quiet
    assert decision.broken == []


def test_disabled_bypass_is_not_a_breakage() -> None:
    """Обход выключен — значит ничего и не сломалось, так и задумано."""
    decision = decide(active=False)

    assert decision.quiet
    assert decision.broken == ["Discord"]


def test_breakage_is_reported() -> None:
    decision = decide()

    assert "Discord" in decision.message
    assert decision.switch_to == ""


def test_switching_is_offered_only_when_asked() -> None:
    assert decide(favorites=["general (ALT2)"]).switch_to == ""


def test_switches_to_the_next_favorite() -> None:
    decision = decide(autoswitch=True, favorites=["general (ALT)", "general (ALT2)"])

    assert decision.switch_to == "general (ALT2)", "текущую стратегию пробовать заново незачем"
    assert "general (ALT2)" in decision.message


def test_already_tried_strategies_are_skipped() -> None:
    decision = decide(
        autoswitch=True,
        favorites=["general (ALT2)", "general (ALT3)"],
        tried=["general (ALT2)"],
    )

    assert decision.switch_to == "general (ALT3)"


def test_without_favorites_it_says_so_instead_of_guessing() -> None:
    """Перебирать все стратегии вслепую — это подбор, у него свой экран."""
    decision = decide(autoswitch=True, favorites=[])

    assert decision.switch_to == ""
    assert "звёздочкой" in decision.message or "подбор" in decision.message


def test_it_gives_up_after_a_few_attempts() -> None:
    decision = decide(
        autoswitch=True,
        favorites=["a", "b", "c", "d", "e"],
        tried=["a", "b", "c"],
    )

    assert decision.switch_to == ""
    assert "подбор" in decision.message


def test_candidate_skips_current_and_tried() -> None:
    assert watch.next_candidate(["a", "b", "c"], current="a", tried=["b"]) == "c"
    assert watch.next_candidate(["a"], current="a", tried=[]) == ""
