"""Тесты движка правил на синтетических снимках системы."""

from __future__ import annotations

import pytest

from app.core.diagnostics.collectors import (
    ProxyInfo,
    SystemFacts,
    find_conflicting_services,
    find_vpn_services,
)
from app.core.diagnostics.rules import Severity, evaluate, problems


def healthy_facts() -> SystemFacts:
    """Снимок полностью исправной системы — отправная точка для тестов."""
    return SystemFacts(
        os_version="Windows 10",
        is_admin=True,
        bfe_running=True,
        tcp_timestamps=True,
        proxy=ProxyInfo(enabled=False),
        core_present=True,
        core_version="1.10.3",
        core_path=r"D:\Code\ZapretXmel\core",
        strategy_count=22,
        available_strategies=["general", "general (ALT)", "discord"],
        windivert_driver_present=True,
        service_state="running",
        service_strategy="general",
        windivert_state="running",
        winws_count=1,
        ipset_mode="loaded",
        user_list_counts={"list-general-user.txt": 5},
    )


def find(facts: SystemFacts, finding_id: str):
    return next((f for f in evaluate(facts) if f.id == finding_id), None)


def test_healthy_system_has_no_problems() -> None:
    facts = healthy_facts()

    assert problems(evaluate(facts)) == []


def test_findings_are_sorted_by_severity() -> None:
    facts = healthy_facts()
    facts.is_admin = False
    facts.tcp_timestamps = False

    order = ["error", "warning", "info", "ok"]
    severities = [finding.severity for finding in evaluate(facts)]

    assert severities == sorted(severities, key=order.index)


def test_missing_admin_is_an_error() -> None:
    facts = healthy_facts()
    facts.is_admin = False

    finding = find(facts, "admin")

    assert finding is not None
    assert finding.severity is Severity.ERROR


def test_stopped_bfe_is_an_error() -> None:
    facts = healthy_facts()
    facts.bfe_running = False

    assert find(facts, "bfe").severity is Severity.ERROR


def test_disabled_timestamps_offers_a_fix() -> None:
    facts = healthy_facts()
    facts.tcp_timestamps = False

    finding = find(facts, "tcp_timestamps")

    assert finding.severity is Severity.WARNING
    assert finding.fix == "enable_tcp_timestamps"


def test_enabled_proxy_offers_a_fix() -> None:
    facts = healthy_facts()
    facts.proxy = ProxyInfo(enabled=True, server="127.0.0.1:8080")

    finding = find(facts, "proxy")

    assert finding.severity is Severity.WARNING
    assert "127.0.0.1:8080" in finding.title
    assert finding.fix == "disable_proxy"


def test_conflicting_services_are_reported() -> None:
    facts = healthy_facts()
    facts.conflicting_services = ["Killer", "SmartByte"]

    finding = find(facts, "conflicting_services")

    assert finding.severity is Severity.ERROR
    assert "Killer" in finding.title


def test_other_dpi_tool_is_an_error() -> None:
    facts = healthy_facts()
    facts.conflicting_processes = ["GoodbyeDPI"]

    assert find(facts, "conflicting_processes").severity is Severity.ERROR


def test_onedrive_path_is_an_error() -> None:
    facts = healthy_facts()
    facts.path_in_onedrive = True

    assert find(facts, "path").severity is Severity.ERROR


def test_cyrillic_path_is_only_a_warning() -> None:
    """Кириллица мешает не всегда, поэтому это предупреждение, а не ошибка."""
    facts = healthy_facts()
    facts.path_has_cyrillic = True

    assert find(facts, "path").severity is Severity.WARNING


def test_onedrive_outranks_cyrillic() -> None:
    facts = healthy_facts()
    facts.path_in_onedrive = True
    facts.path_has_cyrillic = True

    assert find(facts, "path").severity is Severity.ERROR


def test_service_running_without_process_is_an_error() -> None:
    """Служба есть, а winws нет — верный признак того, что обход падает при старте."""
    facts = healthy_facts()
    facts.winws_count = 0

    assert find(facts, "bypass").severity is Severity.ERROR


def test_bypass_off_is_merely_informational() -> None:
    facts = healthy_facts()
    facts.winws_count = 0
    facts.service_state = "stopped"

    assert find(facts, "bypass").severity is Severity.INFO


def test_portable_run_without_service_is_fine() -> None:
    facts = healthy_facts()
    facts.service_state = "not_installed"
    facts.service_strategy = ""

    assert find(facts, "bypass").severity is Severity.OK


def test_foreign_install_warns() -> None:
    facts = healthy_facts()
    facts.foreign_install = r"D:\zapret"
    facts.foreign_source = "на неё настроена служба zapret"

    finding = find(facts, "foreign_install")

    assert finding.severity is Severity.WARNING
    assert r"D:\zapret" in finding.title


def test_foreign_install_silences_the_vanished_strategy_warning() -> None:
    """Имя стратегии принадлежит чужой папке — жаловаться на пропажу незачем."""
    facts = healthy_facts()
    facts.service_strategy = "general (их собственная)"
    facts.foreign_install = r"D:\zapret"

    assert find(facts, "strategy_missing") is None


def test_vanished_strategy_warns() -> None:
    """Служба осталась со стратегией, которой после обновления ядра уже нет."""
    facts = healthy_facts()
    facts.service_strategy = "general (переименованная)"

    assert find(facts, "strategy_missing").severity is Severity.WARNING


def test_present_strategy_produces_no_finding() -> None:
    assert find(healthy_facts(), "strategy_missing") is None


def test_multiple_winws_instances_warn_with_fix() -> None:
    facts = healthy_facts()
    facts.winws_count = 3

    finding = find(facts, "multiple_winws")

    assert finding.severity is Severity.WARNING
    assert finding.fix == "stop_extra_winws"


def test_single_instance_produces_no_finding() -> None:
    assert find(healthy_facts(), "multiple_winws") is None


def test_hanging_windivert_is_reported() -> None:
    facts = healthy_facts()
    facts.windivert_state = "stop_pending"

    assert find(facts, "windivert_pending").severity is Severity.ERROR


def test_missing_core_is_an_error() -> None:
    facts = healthy_facts()
    facts.core_present = False

    assert find(facts, "core").severity is Severity.ERROR


def test_checks_depending_on_core_are_skipped_without_it() -> None:
    """Пока ядра нет, незачем ругаться на драйвер и пути внутри него."""
    facts = healthy_facts()
    facts.core_present = False
    facts.windivert_driver_present = False

    assert find(facts, "windivert_file") is None
    assert find(facts, "path") is None


def test_missing_windivert_driver_is_an_error() -> None:
    facts = healthy_facts()
    facts.windivert_driver_present = False

    assert find(facts, "windivert_file").severity is Severity.ERROR


def test_installed_but_inactive_vpn_is_not_reported() -> None:
    """Установленный клиент сам по себе не мешает — важен только активный туннель."""
    facts = healthy_facts()
    facts.vpn_services = ["WireGuardVPN"]

    assert find(facts, "vpn") is None


def test_active_vpn_is_a_warning() -> None:
    """Через туннель любые замеры меряют VPN, а не провайдера."""
    facts = healthy_facts()
    facts.active_vpn = "AmneziaVPN (WireGuard Tunnel)"

    finding = find(facts, "vpn")

    assert finding is not None
    assert finding.severity is Severity.WARNING
    assert "AmneziaVPN" in finding.title


# --- сопоставление имён служб ------------------------------------------


def test_killer_service_is_matched() -> None:
    assert find_conflicting_services(["KillerNetworkService", "Dhcp"]) == ["Killer"]


def test_plain_intel_service_is_not_a_conflict() -> None:
    """Служб со словом Intel на обычной машине много — нужны все слова сразу."""
    assert find_conflicting_services(["Intel(R) Audio Service", "igfxCUIService"]) == []


def test_full_intel_connectivity_name_is_a_conflict() -> None:
    names = ["Intel(R) Connectivity Network Service"]

    assert find_conflicting_services(names) == ["Intel Connectivity Network Service"]


def test_check_point_matches_either_marker() -> None:
    assert find_conflicting_services(["TracSrvWrapper"]) == ["Check Point"]
    assert find_conflicting_services(["EPWD"]) == ["Check Point"]


def test_clean_system_has_no_conflicts() -> None:
    assert find_conflicting_services(["Dhcp", "Dnscache", "BFE", "Spooler"]) == []


def test_vpn_services_found_case_insensitively() -> None:
    assert find_vpn_services(["OpenVPNService", "Dhcp", "vpnagent"]) == [
        "OpenVPNService",
        "vpnagent",
    ]


@pytest.mark.parametrize("state", ["running", "stopped"])
def test_windivert_states_other_than_pending_are_quiet(state: str) -> None:
    facts = healthy_facts()
    facts.windivert_state = state

    assert find(facts, "windivert_pending") is None
