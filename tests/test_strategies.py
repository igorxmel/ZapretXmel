"""Тесты каталога стратегий: что считается стратегией и в каком порядке выводится."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.core import paths, strategies

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


# --- свои стратегии -----------------------------------------------------


@pytest.fixture
def core_with_strategy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Папка ядра с одной настоящей стратегией из фикстур."""
    core = tmp_path / "core"
    (core / "bin").mkdir(parents=True)
    (core / "lists").mkdir()
    shutil.copy2(BUNDLE_NEW / "general (ALT).bat", core / "general (ALT).bat")

    monkeypatch.setattr(paths, "core_dir", lambda: core)
    return core


def test_duplicate_keeps_the_original(core_with_strategy: Path) -> None:
    """Копия нужна, чтобы править не ломая исходную — та обязана уцелеть."""
    copy = strategies.duplicate("general (ALT)")

    assert copy.exists()
    assert (core_with_strategy / "general (ALT).bat").exists()
    assert copy.read_bytes() == (core_with_strategy / "general (ALT).bat").read_bytes()


def test_copy_is_marked_as_own(core_with_strategy: Path) -> None:
    copy = strategies.duplicate("general (ALT)")

    assert strategies.is_own(copy.stem)
    assert strategies.load_one(copy.stem) is not None, "копия должна читаться как стратегия"


def test_second_copy_does_not_overwrite_the_first(core_with_strategy: Path) -> None:
    first = strategies.duplicate("general (ALT)")
    second = strategies.duplicate("general (ALT)")

    assert first != second
    assert first.exists() and second.exists()


def test_added_file_is_checked_before_copying(
    core_with_strategy: Path, tmp_path: Path
) -> None:
    """Файл, который не разбирается, в список попадать не должен.

    Иначе он сломается при запуске обхода — то есть тогда, когда причину уже
    не связать с добавлением.
    """
    junk = tmp_path / "не стратегия.bat"
    junk.write_text("@echo off\r\necho привет\r\n", encoding="cp866")

    with pytest.raises(ValueError, match="winws"):
        strategies.add(junk)

    assert not list(core_with_strategy.glob("не стратегия*"))


def test_added_file_appears_in_the_list(core_with_strategy: Path, tmp_path: Path) -> None:
    source = tmp_path / "мояа.bat"
    shutil.copy2(BUNDLE_NEW / "general (ALT2).bat", source)

    added = strategies.add(source)

    assert added.parent == core_with_strategy
    assert added.stem in {path.stem for path in strategies.discover()}


def test_adding_without_core_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "core_dir", lambda: tmp_path / "нет такой")

    with pytest.raises(ValueError, match="ядро"):
        strategies.add(BUNDLE_NEW / "general (ALT).bat")
