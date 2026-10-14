"""Тесты профилей приложений.

Профиль — это фильтр по портам и адресам, выведенный из наблюдаемого трафика.
Проверяется, что шум отсеивается, флаги уровня ядра попадают в начало, а
способ обхода берётся из стратегии, а не придумывается.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from app.core import appprofile
from app.core.appprofile import Endpoint, Profile, build_profile, is_useful, safe_name
from app.core.batfile import parse_bat

FIXTURES = Path(__file__).parent / "fixtures" / "bundle_1_10_3"


@pytest.fixture
def spec():
    return parse_bat(FIXTURES / "general.bat", root=FIXTURES)


def endpoints() -> list[Endpoint]:
    return [
        Endpoint("104.16.1.5", 443, "tcp"),
        Endpoint("104.16.1.6", 443, "tcp"),
        Endpoint("162.159.130.234", 50002, "udp"),
    ]


# --- отбор адресов ------------------------------------------------------


@pytest.mark.parametrize("address", ["104.16.1.5", "8.8.8.8", "192.168.1.10"])
def test_real_addresses_are_kept(address: str) -> None:
    assert is_useful(address)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "0.0.0.0", "169.254.1.1", "224.0.0.251", "255.255.255.255", ""],
)
def test_service_addresses_are_skipped(address: str) -> None:
    assert not is_useful(address)


def test_ipv6_is_skipped() -> None:
    """Списки адресов в сборке составлены для IPv4."""
    assert not is_useful("2606:4700::1111")


# --- сборка профиля -----------------------------------------------------


def test_profile_splits_ports_by_protocol() -> None:
    profile = build_profile("игра", endpoints())

    assert profile.tcp_ports == [443]
    assert profile.udp_ports == [50002]
    assert len(profile.addresses) == 3


def test_rare_endpoints_are_dropped() -> None:
    """В записи оседает телеметрия и проверки обновлений — им в фильтре не место."""
    points = [*endpoints(), Endpoint("8.8.8.8", 53, "udp")]
    counts = Counter({point.key: 5 for point in points})
    counts[("8.8.8.8", 53, "udp")] = 1

    profile = build_profile("игра", points, min_hits=2, counts=counts)

    assert "8.8.8.8" not in profile.addresses
    assert 53 not in profile.udp_ports


def test_profile_without_data_is_empty() -> None:
    assert build_profile("пусто", []).is_empty


def test_profile_with_addresses_only_is_empty() -> None:
    """Без портов фильтр не собрать — перехватывать нечего."""
    assert Profile(name="x", addresses=["1.2.3.4"]).is_empty


def test_summary_is_readable() -> None:
    assert "адресов 3" in build_profile("игра", endpoints()).summary


# --- выбор способа обхода -----------------------------------------------


def test_template_prefers_any_protocol_section(spec) -> None:
    """Протокол приложения заранее неизвестен — нужна секция на любой трафик."""
    section = appprofile.pick_template(spec)

    assert section is not None
    assert any(arg.startswith(appprofile.ANY_PROTOCOL_FLAG) for arg in section.args)


def test_template_falls_back_to_last_section() -> None:
    from app.core.batfile import Section, StrategySpec

    spec = StrategySpec(
        name="без any", path=Path("x"), argv=[], sections=[Section(["--a"]), Section(["--b"])]
    )

    assert appprofile.pick_template(spec).args == ["--b"]


def test_desync_args_drop_filters(spec) -> None:
    section = appprofile.pick_template(spec)

    cleaned = appprofile.desync_args(section)

    assert cleaned
    assert not any(a.startswith(("--filter-", "--ipset", "--hostlist", "--wf-")) for a in cleaned)


# --- командная строка ---------------------------------------------------


@pytest.fixture
def lists_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(appprofile.paths, "core_lists", lambda: tmp_path)
    monkeypatch.setattr(appprofile.paths, "data_dir", lambda: tmp_path)
    return tmp_path


def test_argv_starts_with_kernel_flags(lists_dir: Path, spec) -> None:
    """Флаги уровня ядра действуют на всю команду и должны идти первыми."""
    argv = appprofile.to_argv(build_profile("игра", endpoints()), spec)

    assert argv[0].startswith("--wf-")
    first_filter = next(i for i, arg in enumerate(argv) if arg.startswith("--filter-"))
    assert all(not argv[i].startswith("--wf-") for i in range(first_filter, len(argv)))


def test_argv_has_section_per_protocol(lists_dir: Path, spec) -> None:
    argv = appprofile.to_argv(build_profile("игра", endpoints()), spec)

    assert argv.count("--new") == 1, "TCP и UDP — две отдельные секции"
    assert any(a.startswith("--filter-tcp=") for a in argv)
    assert any(a.startswith("--filter-udp=") for a in argv)


def test_argv_skips_missing_protocol(lists_dir: Path, spec) -> None:
    only_tcp = [Endpoint("104.16.1.5", 443, "tcp")]

    argv = appprofile.to_argv(build_profile("игра", only_tcp), spec)

    assert "--new" not in argv
    assert not any(a.startswith("--wf-udp") for a in argv)


def test_addresses_are_written_to_ipset(lists_dir: Path, spec) -> None:
    profile = build_profile("игра", endpoints())

    appprofile.to_argv(profile, spec)

    content = appprofile.ipset_file(profile).read_text(encoding="utf-8")
    assert "104.16.1.5" in content
    assert "162.159.130.234" in content


def test_profile_becomes_runnable_strategy(lists_dir: Path, spec) -> None:
    built = appprofile.as_spec(build_profile("игра", endpoints()), spec)

    assert built.argv
    assert len(built.sections) == 2
    assert "профиль" in built.name


def test_strategy_without_sections_is_rejected(lists_dir: Path) -> None:
    from app.core.batfile import StrategySpec

    empty = StrategySpec(name="пустая", path=Path("x"), argv=[], sections=[])

    with pytest.raises(ValueError, match="секции"):
        appprofile.to_argv(build_profile("игра", endpoints()), empty)


# --- хранение -----------------------------------------------------------


def test_profile_survives_save_and_load(lists_dir: Path) -> None:
    original = build_profile("Моя игра", endpoints(), exe=r"D:\Games\game.exe")

    appprofile.save(original)
    restored = appprofile.load_all()

    assert len(restored) == 1
    assert restored[0].name == "Моя игра"
    assert restored[0].addresses == original.addresses
    assert restored[0].exe == original.exe


def test_deleted_profile_disappears(lists_dir: Path) -> None:
    appprofile.save(build_profile("временный", endpoints()))

    appprofile.delete("временный")

    assert appprofile.load_all() == []


def test_missing_directory_gives_nothing(lists_dir: Path) -> None:
    assert appprofile.load_all() == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Моя игра", "Моя игра"),
        ("game/../etc", "game_.._etc"),
        ("a:b*c?", "a_b_c_"),
        ("", "профиль"),
    ],
)
def test_names_are_made_safe_for_filenames(raw: str, expected: str) -> None:
    assert safe_name(raw) == expected
