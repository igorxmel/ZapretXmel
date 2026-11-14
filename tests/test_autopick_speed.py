"""Подбор не должен ждать таймауты по очереди.

Адреса внутри сервиса проверялись строго один за другим, и стратегия, которая
что-то не пропускала, ждала таймаут на каждый закрытый адрес подряд: в журнале
general (ALT5) заняла 45 секунд при обычных 10.
"""

from __future__ import annotations

import time

from app.core.probe import autopick, services
from app.core.probe.http import TargetResult
from app.core.probe.services import Service, ServiceResult
from app.core.probe.targets import Target


def _service(count: int) -> Service:
    targets = [Target(name=f"t{i}", url=f"https://t{i}.example") for i in range(count)]
    return Service(name="YouTube", targets=targets)


def test_picker_asks_services_to_probe_targets_in_parallel(monkeypatch) -> None:
    asked = []
    monkeypatch.setattr(
        services,
        "check",
        lambda service, timeout, parallel=1: asked.append(parallel)
        or ServiceResult(service=service.name, checks=[]),
    )

    autopick.AutoPicker(parallel=8)._check_services([_service(4)])

    assert asked == [8]


def test_closed_targets_time_out_together_not_one_after_another(monkeypatch) -> None:
    """Четыре адреса по 0,3 с таймаута — около 0,3 с, а не 1,2."""

    def slow(target, timeout):
        time.sleep(0.3)
        return TargetResult(target=target, probes=[], ping_ms=None)

    monkeypatch.setattr(services, "check_target", slow)

    started = time.monotonic()
    autopick.AutoPicker(parallel=8)._check_services([_service(4)])

    assert time.monotonic() - started < 0.9


def test_protocols_and_ping_of_one_target_run_together(monkeypatch) -> None:
    """HTTP, TLS и пинг закрытого адреса ждали друг за другом — теперь вместе."""
    from app.core.probe import http

    def slow_probe(target, name, args, timeout):
        time.sleep(0.3)
        return http.ProbeResult(target=target.name, protocol=name, outcome=http.Outcome.ERROR)

    def slow_ping(host, timeout_ms):
        time.sleep(0.3)

    monkeypatch.setattr(http, "supported_protocols", lambda: [("HTTP", []), ("TLS1.2", [])])
    monkeypatch.setattr(http, "probe", slow_probe)
    monkeypatch.setattr(http, "ping", slow_ping)

    started = time.monotonic()
    result = http.check_target(Target(name="t", url="https://t.example"))

    assert time.monotonic() - started < 0.7
    assert [item.protocol for item in result.probes] == ["HTTP", "TLS1.2"]
