"""Свой адрес в сетевых проверках: нормализация и то, что запускается.

Введённый человеком текст попадает в аргументы `tracert` и в запросы, поэтому
строгость нормализации — не придирка, а граница: ключ командной строки не должен
пройти под видом имени сайта.
"""

from __future__ import annotations

import pytest

from app.core import nettools


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("instagram.com", "instagram.com"),
        ("  https://www.Instagram.com/user?x=1  ", "www.instagram.com"),
        ("chat.openai.com:443", "chat.openai.com"),
        ("пример.рф", "xn--e1afmkfd.xn--p1ai"),
        ("1.1.1.1", "1.1.1.1"),
        ("user@host.com", "host.com"),
    ],
)
def test_pasted_forms_reduce_to_a_clean_host(text: str, expected: str) -> None:
    assert nettools.normalize_host(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "   ", "http://", "-h 1", "-d", "a b", "evil.com & calc", "host.com;rm", "a..b",
     "-bad.com", "bad-.com", "name_with_underscore.com", "x" * 300 + ".com", "[::1]"],
)
def test_anything_that_could_be_an_option_or_is_not_a_name_is_rejected(text: str) -> None:
    """`-h 1` стало бы ключом `tracert`: пропускать такое нельзя."""
    assert nettools.normalize_host(text) == ""


def test_custom_host_is_checked_next_to_a_free_control_site(monkeypatch) -> None:
    """Без свободного соседа «не открывается» ничего не говорит о блокировке."""
    from app.core.probe import layers

    seen: list[str] = []

    def fake_check(host, honest=None):
        seen.append(host)
        return layers.LayerResult(host, layers.Layer.OK)

    monkeypatch.setattr(layers, "check", fake_check)
    monkeypatch.setattr(nettools, "_resolve_over_https", lambda host: [])

    nettools.where_blocked("instagram.com")

    assert seen == ["instagram.com", nettools.CONTROL_HOST]


def test_without_a_custom_host_the_typical_sites_are_used(monkeypatch) -> None:
    from app.core.probe import layers

    seen: list[str] = []
    monkeypatch.setattr(
        layers, "check", lambda host, honest=None: seen.append(host) or layers.LayerResult(
            host, layers.Layer.OK
        ),
    )
    monkeypatch.setattr(nettools, "_resolve_over_https", lambda host: [])

    nettools.where_blocked()

    assert tuple(seen) == nettools.LAYER_HOSTS


def test_the_control_site_is_not_checked_twice(monkeypatch) -> None:
    from app.core.probe import layers

    seen: list[str] = []
    monkeypatch.setattr(
        layers, "check", lambda host, honest=None: seen.append(host) or layers.LayerResult(
            host, layers.Layer.OK
        ),
    )
    monkeypatch.setattr(nettools, "_resolve_over_https", lambda host: [])

    nettools.where_blocked(nettools.CONTROL_HOST)

    assert tuple(seen) == nettools.LAYER_HOSTS


def test_what_the_tooltip_shows_is_what_actually_runs(monkeypatch) -> None:
    """Подсказка строится из тех же списков аргументов, что и запуск."""
    ran: list[list[str]] = []

    class Done:
        returncode = 0
        stdout = "Pinging\n  1     1 ms  10.0.0.1\n  2     2 ms  1.1.1.1\n"
        stderr = ""

    def fake_run(args, timeout=40):
        ran.append(args)
        return Done()

    monkeypatch.setattr(nettools, "_run", fake_run)
    monkeypatch.setattr(nettools, "icmp_works", lambda: True)
    monkeypatch.setattr(nettools, "_answers_ping", lambda host, wait_ms=1200: True)

    nettools.flush_dns()
    nettools.trace("instagram.com")
    nettools.check_mtu()

    assert nettools.shown(ran[0]) == nettools.shown(nettools.flush_command())
    assert nettools.shown(ran[0]) == "ipconfig /flushdns"
    assert nettools.shown(ran[1]) == nettools.shown(nettools.trace_command("instagram.com"))
    assert nettools.shown(ran[2]) == nettools.shown(nettools.mtu_command())
