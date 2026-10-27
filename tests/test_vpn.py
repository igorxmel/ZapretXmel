"""Тесты распознавания активного VPN-подключения."""

from __future__ import annotations

import socket
from collections import namedtuple

import pytest

from app.core.diagnostics import vpn
from app.core.diagnostics.vpn import VpnInfo, adapter_for_address, looks_like_tunnel

Addr = namedtuple("Addr", "family address")


@pytest.mark.parametrize(
    "name",
    [
        "AmneziaVPN",
        "WireGuard Tunnel",
        "OpenVPN TAP-Windows6",
        "Tailscale",
        "ProtonVPN TUN",
        "NordLynx",
        "Mullvad",
        "Cloudflare WARP",
        "ZeroTier One",
        "wintun userspace tunnel",
    ],
)
def test_tunnel_adapters_are_recognised(name: str) -> None:
    assert looks_like_tunnel(name)


@pytest.mark.parametrize(
    "name",
    [
        "Ethernet",
        "Realtek PCIe GbE Family Controller",
        "Wi-Fi",
        "Intel(R) Wireless-AC 9560",
        "VirtualBox Host-Only Ethernet Adapter",
        "",
    ],
)
def test_ordinary_adapters_are_not_tunnels(name: str) -> None:
    assert not looks_like_tunnel(name)


def test_description_also_counts() -> None:
    """Имя подключения может быть нейтральным, а описание — выдавать туннель."""
    assert looks_like_tunnel("Подключение 7", "WireGuard Tunnel")


def test_adapter_is_found_by_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        vpn.psutil,
        "net_if_addrs",
        lambda: {
            "Ethernet": [Addr(socket.AF_INET, "192.168.1.50")],
            "AmneziaVPN": [Addr(socket.AF_INET, "10.8.1.2")],
        },
    )

    assert adapter_for_address("10.8.1.2") == "AmneziaVPN"
    assert adapter_for_address("192.168.1.50") == "Ethernet"


def test_unknown_address_gives_no_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vpn.psutil, "net_if_addrs", dict)

    assert adapter_for_address("10.8.1.2") == ""
    assert adapter_for_address("") == ""


def test_fast_detection_reports_tunnel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vpn, "outbound_address", lambda: "10.8.1.2")
    monkeypatch.setattr(
        vpn.psutil,
        "net_if_addrs",
        lambda: {"AmneziaVPN": [Addr(socket.AF_INET, "10.8.1.2")]},
    )

    found = vpn.detect_fast()

    assert found is not None
    assert found.adapter == "AmneziaVPN"


def test_fast_detection_quiet_on_plain_ethernet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vpn, "outbound_address", lambda: "192.168.1.50")
    monkeypatch.setattr(
        vpn.psutil,
        "net_if_addrs",
        lambda: {"Ethernet": [Addr(socket.AF_INET, "192.168.1.50")]},
    )

    monkeypatch.setattr(vpn, "_descriptions", {})
    monkeypatch.setattr(vpn, "_adapter_descriptions", lambda: {"Ethernet": "Realtek PCIe GbE"})

    assert vpn.detect_fast() is None


def test_fast_detection_knows_tunnel_with_neutral_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clash Verge называет адаптер «Meta»: по имени не узнать, по описанию — да."""
    monkeypatch.setattr(vpn, "outbound_address", lambda: "198.18.0.1")
    monkeypatch.setattr(
        vpn.psutil, "net_if_addrs", lambda: {"Meta": [Addr(socket.AF_INET, "198.18.0.1")]}
    )
    monkeypatch.setattr(vpn, "_descriptions", {})
    monkeypatch.setattr(vpn, "_adapter_descriptions", lambda: {"Meta": "Meta Tunnel"})

    found = vpn.detect_fast()

    assert found is not None
    assert found.label == "Meta (Meta Tunnel)"


def test_adapter_descriptions_are_asked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Опрос идёт каждые секунды: PowerShell на каждом шаге недопустим."""
    calls: list[int] = []
    monkeypatch.setattr(vpn, "_descriptions", {})
    monkeypatch.setattr(vpn, "_adapter_descriptions", lambda: calls.append(1) or {})

    vpn.adapter_description("Ethernet")
    vpn.adapter_description("Ethernet")

    assert len(calls) == 1


def test_detect_prefers_default_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """Маршрут по умолчанию — точный ответ на вопрос, куда уходит трафик."""
    monkeypatch.setattr(vpn, "_default_route_adapter", lambda: ("AmneziaVPN", "WireGuard Tunnel"))

    found = vpn.detect()

    assert found is not None
    assert found.label == "AmneziaVPN (WireGuard Tunnel)"


def test_detect_falls_back_when_powershell_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vpn, "_default_route_adapter", lambda: ("", ""))
    monkeypatch.setattr(vpn, "outbound_address", lambda: "10.8.1.2")
    monkeypatch.setattr(
        vpn.psutil,
        "net_if_addrs",
        lambda: {"Tailscale": [Addr(socket.AF_INET, "10.8.1.2")]},
    )

    found = vpn.detect()

    assert found is not None
    assert found.adapter == "Tailscale"


def test_detect_quiet_when_route_is_ordinary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vpn, "_default_route_adapter", lambda: ("Ethernet", "Realtek PCIe GbE"))
    monkeypatch.setattr(vpn, "_descriptions", {"Ethernet": "Realtek PCIe GbE"})
    monkeypatch.setattr(vpn, "outbound_address", lambda: "192.168.1.50")
    monkeypatch.setattr(
        vpn.psutil,
        "net_if_addrs",
        lambda: {"Ethernet": [Addr(socket.AF_INET, "192.168.1.50")]},
    )

    assert vpn.detect() is None


def test_label_without_description() -> None:
    assert VpnInfo(adapter="Tailscale").label == "Tailscale"


def test_label_skips_duplicate_description() -> None:
    assert VpnInfo(adapter="AmneziaVPN", description="amneziavpn").label == "AmneziaVPN"
