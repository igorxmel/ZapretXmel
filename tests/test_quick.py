"""Тесты быстрой проверки «работает ли сейчас».

Вердикт читает человек, у которого только что что-то не открылось, поэтому
проверяется именно он: что названо сломанным, что рабочим и в каком случае
сказано «работает всё».
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.core.probe import http, quick, services
from app.core.probe.services import CheckResult, Service, ServiceResult
from app.core.probe.targets import Target


def result(name: str, ok: int, total: int) -> ServiceResult:
    checks = [CheckResult(name=f"{name}-{i}", ok=i < ok, detail="") for i in range(total)]
    return ServiceResult(service=name, checks=checks)


def test_everything_works_when_all_services_pass() -> None:
    check = quick.QuickCheck([result("YouTube", 4, 4), result("Discord", 3, 3)])

    assert check.everything_works
    assert check.broken == []
    assert "всё работает" in check.verdict


def test_partial_service_counts_as_broken() -> None:
    """Discord, у которого открывается сайт, но не подключается клиент, не работает."""
    check = quick.QuickCheck([result("Discord", 2, 3), result("YouTube", 4, 4)])

    assert not check.everything_works
    assert check.broken == ["Discord"]
    assert check.working == ["YouTube"]
    assert "не работает: Discord" in check.verdict
    assert "работает: YouTube" in check.verdict


def test_nothing_works_is_said_plainly() -> None:
    check = quick.QuickCheck([result("YouTube", 0, 4), result("Discord", 0, 3)])

    assert check.verdict == "не работает ничего из проверенного"


def test_empty_check_says_there_was_nothing_to_probe() -> None:
    assert quick.QuickCheck().verdict.startswith("проверять нечего")


def test_run_without_targets_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quick.services, "discover", lambda: [])

    assert quick.run().results == []


def test_run_checks_every_service(monkeypatch: pytest.MonkeyPatch) -> None:
    found = [Service(name="YouTube"), Service(name="Discord", kind="discord")]
    monkeypatch.setattr(quick.services, "discover", lambda: found)
    monkeypatch.setattr(quick.coverage, "uncovered_target_names", frozenset)
    monkeypatch.setattr(
        quick.services, "check", lambda service, timeout, parallel: result(service.name, 1, 1)
    )

    check = quick.run()

    assert [item.service for item in check.results] == ["YouTube", "Discord"]


def test_targets_are_probed_in_parallel_only_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """В подборе проверки идут по очереди: иначе время перестаёт быть сравнимым."""
    seen: list[str] = []

    def fake_check_target(target, timeout):
        seen.append(target.name)
        return type("Result", (), {"probes": [], "ping_ms": 1.0})()

    monkeypatch.setattr(services, "check_target", fake_check_target)

    service = Service(
        name="YouTube",
        targets=[
            services.Target(name="a", ping_host="a.invalid"),
            services.Target(name="b", ping_host="b.invalid"),
        ],
    )

    outcome = services.check(service, timeout=1)

    assert seen == ["a", "b"]
    assert outcome.total == 2


def ping_only(name: str, ok: int, total: int) -> ServiceResult:
    """Группа из одних пингов — та самая «Public DNS (PING-only)» апстрима."""
    checks = [CheckResult(name=f"{name}-{i}", ok=i < ok, detail="") for i in range(total)]
    return ServiceResult(service=name, checks=checks, measures_bypass=False)


def test_failed_pings_do_not_make_the_verdict_say_broken() -> None:
    """winws не трогает ICMP: пинг одинаков с обходом и без него.

    У многих ICMP режет брандмауэр, и вердикт объявлял «не работает Public
    DNS (PING-only)» при полностью рабочем обходе.
    """
    check = quick.QuickCheck(
        [result("YouTube", 4, 4), ping_only("Public DNS (PING-only)", 0, 4)]
    )

    assert check.everything_works
    assert check.broken == []
    assert "Public DNS" not in check.verdict
    assert "обхода это не касается" in check.verdict


def test_passing_pings_are_not_mentioned_at_all() -> None:
    """Сказать о пингах стоит только тогда, когда они не прошли."""
    check = quick.QuickCheck(
        [result("YouTube", 4, 4), ping_only("Public DNS (PING-only)", 4, 4)]
    )

    assert check.verdict == "всё работает: YouTube"


def test_ping_only_service_is_marked_by_target_kind() -> None:
    """Признак — формат цели из файла, а не название группы: его переименуют."""
    pings = Service(
        name="Public DNS (PING-only)",
        targets=[services.Target(name="cf", ping_host="1.1.1.1")],
    )
    mixed = Service(
        name="Public DNS (PING-only)",
        targets=[
            services.Target(name="cf", ping_host="1.1.1.1"),
            services.Target(name="site", url="https://example.com"),
        ],
    )

    assert not pings.measures_bypass
    assert mixed.measures_bypass


# --- цели вне списков ------------------------------------------------------------


def _targets(service: str, *checks: tuple[str, bool]) -> ServiceResult:
    return ServiceResult(
        service=service,
        checks=[CheckResult(name, ok, "", target=name) for name, ok in checks],
    )


def test_target_outside_lists_does_not_break_the_service() -> None:
    check = quick.QuickCheck(
        [_targets("Google", ("GoogleMain", False), ("GoogleStatic", True))],
        ignored=frozenset({"GoogleMain"}),
    )

    assert check.broken == []
    assert check.working == ["Google"]
    assert check.everything_works
    assert "не открылось вне списков: GoogleMain" in check.verdict


def test_outside_lists_is_explained_in_plain_words() -> None:
    """«Не открылось вне списков: CloudflareCDN» на экране понять было нельзя."""
    check = quick.QuickCheck(
        [_targets("Cloudflare", ("CloudflareCDN", False), ("Cloudflare", True))],
        ignored=frozenset({"CloudflareCDN"}),
    )

    assert len(check.notes) == 1
    assert "CloudflareCDN" in check.notes[0]
    assert "нет в списках обхода" in check.notes[0]
    assert "вне списков" not in check.notes[0]


def test_nothing_to_explain_when_all_listed_targets_pass() -> None:
    check = quick.QuickCheck([_targets("Google", ("GoogleMain", True))])

    assert check.notes == []


def test_service_entirely_outside_lists_is_not_judged() -> None:
    ignored = frozenset({"CloudflareWeb", "CloudflareCDN"})
    check = quick.QuickCheck(
        [
            _targets("Cloudflare", ("CloudflareWeb", True), ("CloudflareCDN", True)),
            result("Discord", 3, 3),
        ],
        ignored=ignored,
    )

    assert check.working == ["Discord"]
    assert check.broken == []


def test_listed_target_still_breaks_the_service() -> None:
    check = quick.QuickCheck(
        [_targets("YouTube", ("YouTubeWeb", False), ("Mine", True))], ignored=frozenset({"Mine"})
    )

    assert check.broken == ["YouTube"]
    assert not check.everything_works


# --- как зовётся curl -------------------------------------------------------------


def test_probe_does_not_fail_on_unreachable_revocation_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Браузер при недоступном сервере отзыва идёт дальше, а curl со Schannel падает."""
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="200", stderr="")

    monkeypatch.setattr(http, "curl_available", lambda: True)
    monkeypatch.setattr(http.subprocess, "run", fake_run)

    http.probe(Target(name="A", url="https://a.example"), "TLS1.2", ("--tlsv1.2",))

    assert http.NO_REVOKE in commands[0]


def test_capabilities_are_measured_once_across_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_run(command, **_kwargs):
        calls.append(1)
        time.sleep(0.01)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(http, "curl_available", lambda: True)
    monkeypatch.setattr(http.subprocess, "run", fake_run)
    http._detect_protocols.cache_clear()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: http.supported_protocols(), range(8)))
    http._detect_protocols.cache_clear()

    assert len(calls) == len(http.PROTOCOLS)
