"""Тесты игрового фильтра: валидация диапазонов и формат файла апстрима."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.batfile import GAME_FILTER_OFF
from app.core.gamefilter import DEFAULT_RANGE, GameFilter, load, save, validate_range


@pytest.mark.parametrize(
    "value",
    ["1024-65535", "443", "1024-1934,1936-65535", "1, 2 , 3", "65535", "1-65535"],
)
def test_valid_ranges(value: str) -> None:
    assert validate_range(value) is not None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0",  # ноль портом не бывает
        "0-100",
        "65536",  # за границей диапазона портов
        "1-65536",
        "100-50",  # конец раньше начала
        "012",  # ведущий ноль апстрим не принимает
        "abc",
        "80,,443",
        "80-",
        "-80",
        "123456",
    ],
)
def test_invalid_ranges(value: str) -> None:
    assert validate_range(value) is None


def test_validate_strips_spaces() -> None:
    assert validate_range(" 80 , 443 ") == "80,443"


def test_disabled_filter_uses_stub_port() -> None:
    game_filter = GameFilter()

    assert game_filter.mode == "disabled"
    assert game_filter.tcp_value == GAME_FILTER_OFF
    assert game_filter.udp_value == GAME_FILTER_OFF


def test_tcp_only_mode_leaves_udp_disabled() -> None:
    game_filter = GameFilter(mode="tcp", tcp_range="1024-65535", udp_range="2048-4096")

    assert game_filter.tcp_value == "1024-65535"
    assert game_filter.udp_value == GAME_FILTER_OFF


def test_udp_only_mode_leaves_tcp_disabled() -> None:
    game_filter = GameFilter(mode="udp", tcp_range="1024-65535", udp_range="2048-4096")

    assert game_filter.tcp_value == GAME_FILTER_OFF
    assert game_filter.udp_value == "2048-4096"


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "game_filter.enabled"
    original = GameFilter(mode="all", tcp_range="1024-2048", udp_range="3000-4000")

    save(original, path)

    assert load(path) == original


def test_save_disabled_removes_flag_file(tmp_path: Path) -> None:
    path = tmp_path / "game_filter.enabled"
    save(GameFilter(mode="all"), path)
    assert path.exists()

    save(GameFilter(mode="disabled"), path)

    assert not path.exists()
    assert load(path).mode == "disabled"


def test_load_missing_file_is_disabled(tmp_path: Path) -> None:
    assert load(tmp_path / "нет-такого").mode == "disabled"


def test_load_ignores_broken_range(tmp_path: Path) -> None:
    """Повреждённое значение не должно ломать запуск — берётся значение по умолчанию."""
    path = tmp_path / "game_filter.enabled"
    path.write_text("mode=all\ntcp=0-99999\nudp=2048-4096\n", encoding="utf-8")

    game_filter = load(path)

    assert game_filter.tcp_range == DEFAULT_RANGE
    assert game_filter.udp_range == "2048-4096"


def test_load_accepts_upstream_bare_keys(tmp_path: Path) -> None:
    """service.bat допускает строку `tcp=` без значения как указание режима."""
    path = tmp_path / "game_filter.enabled"
    path.write_text("tcp=\n", encoding="utf-8")

    assert load(path).mode == "tcp"
