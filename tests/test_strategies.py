"""Тесты каталога стратегий: что считается стратегией и в каком порядке выводится."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import strategies

FIXTURES = Path(__file__).parent / "fixtures"
BUNDLE_NEW = FIXTURES / "bundle_1_10_3"
BUNDLE_OLD = FIXTURES / "bundle_1_6_1"


@pytest.mark.parametrize(
    "name", ["service.bat", "service_install.bat", "check_updates.bat", "SERVICE.BAT"]
)
def test_service_scripts_are_not_strategies(name: str) -> None:
    assert not strategies.is_strategy_file(Path(name))


@pytest.mark.parametrize("name", ["general.bat", "general (ALT).bat", "discord.bat", "моё.bat"])
def test_strategy_files_are_recognised(name: str) -> None:
    assert strategies.is_strategy_file(Path(name))


def test_non_bat_files_are_ignored() -> None:
    assert not strategies.is_strategy_file(Path("list-general.txt"))
    assert not strategies.is_strategy_file(Path("winws.exe"))


def test_order_matches_upstream_menu() -> None:
    """Порядок должен совпадать с меню service.bat: ALT перед ALT2, ALT2 перед ALT10."""
    names = [path.stem for path in strategies.discover(BUNDLE_NEW)]

    assert names[0] == "general"
    assert names.index("general (ALT)") < names.index("general (ALT2)")
    assert names.index("general (ALT2)") < names.index("general (ALT10)")
    assert names.index("general (ALT9)") < names.index("general (ALT10)")


def test_discover_skips_service_scripts() -> None:
    names = [path.name for path in strategies.discover(BUNDLE_NEW)]

    assert "service.bat" not in names
    assert len(names) == 22


def test_discover_handles_old_bundle() -> None:
    names = [path.name for path in strategies.discover(BUNDLE_OLD)]

    assert "service_install.bat" not in names
    assert "check_updates.bat" not in names
    assert "discord.bat" in names


def test_discover_returns_nothing_for_missing_dir(tmp_path: Path) -> None:
    assert strategies.discover(tmp_path / "нет-такой-папки") == []
