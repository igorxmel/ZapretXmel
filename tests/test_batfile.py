"""Тесты парсера стратегий на реальных .bat из двух версий сборки Flowseal.

Версия 1.10.3 — текущая, 1.6.1 — старая (списки лежат в корне, а не в lists/),
на ней проверяется обратная совместимость парсера.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.batfile import (
    BatParseError,
    StrategySpec,
    parse_bat,
    split_sections,
    to_service_binpath,
)

FIXTURES = Path(__file__).parent / "fixtures"
BUNDLE_NEW = FIXTURES / "bundle_1_10_3"
BUNDLE_OLD = FIXTURES / "bundle_1_6_1"


def strategy_files(bundle: Path) -> list[Path]:
    """Стратегии сборки — все .bat, кроме служебных."""
    return sorted(
        path
        for path in bundle.glob("*.bat")
        if not path.name.lower().startswith(("service", "check_updates"))
    )


NEW_STRATEGIES = strategy_files(BUNDLE_NEW)
OLD_STRATEGIES = strategy_files(BUNDLE_OLD)


def test_fixtures_present() -> None:
    assert len(NEW_STRATEGIES) == 22, "ожидались 22 стратегии версии 1.10.3"
    assert len(OLD_STRATEGIES) == 9, "ожидались 9 стратегий версии 1.6.1"


@pytest.mark.parametrize("path", NEW_STRATEGIES + OLD_STRATEGIES, ids=lambda p: p.stem)
def test_every_strategy_parses(path: Path) -> None:
    spec = parse_bat(path)

    assert spec.argv, "аргументы winws не должны быть пустыми"
    assert spec.name == path.stem
    assert not any(arg.endswith("winws.exe") for arg in spec.argv), "exe попал в аргументы"
    assert "^" not in spec.argv, "символ переноса строки не вычищен"


@pytest.mark.parametrize("path", NEW_STRATEGIES + OLD_STRATEGIES, ids=lambda p: p.stem)
def test_no_unexpanded_variables(path: Path) -> None:
    spec = parse_bat(path)
    for arg in spec.argv:
        assert "%" not in arg, f"нераскрытая переменная в {arg!r}"


@pytest.mark.parametrize("path", NEW_STRATEGIES + OLD_STRATEGIES, ids=lambda p: p.stem)
def test_file_arguments_are_absolute(path: Path) -> None:
    """Все ссылки на списки и фейковые пакеты должны стать абсолютными путями."""
    spec = parse_bat(path, root=path.parent)
    for arg in spec.argv:
        _, sep, value = arg.partition("=")
        if not sep or not value.lower().endswith((".txt", ".bin")):
            continue
        assert Path(value).is_absolute(), f"относительный путь остался в {arg!r}"


def test_old_bundle_resolves_lists_against_root() -> None:
    """В 1.6.1 списки лежали в корне и указывались без каталога."""
    spec = parse_bat(BUNDLE_OLD / "general.bat")
    hostlists = [a for a in spec.argv if a.startswith("--hostlist=")]

    assert hostlists
    for arg in hostlists:
        value = Path(arg.split("=", 1)[1])
        assert value.parent == BUNDLE_OLD.resolve()
        assert value.name == "list-general.txt"


def test_new_bundle_resolves_lists_into_lists_dir() -> None:
    """В 1.10.3 пути собираются из %LISTS% и уже абсолютны."""
    spec = parse_bat(BUNDLE_NEW / "general.bat")
    hostlists = [a for a in spec.argv if a.startswith("--hostlist=")]

    assert hostlists
    for arg in hostlists:
        value = Path(arg.split("=", 1)[1])
        assert value.parent.name == "lists"


def test_fake_payloads_point_into_bin() -> None:
    spec = parse_bat(BUNDLE_NEW / "general.bat")
    fakes = [a for a in spec.argv if a.startswith("--dpi-desync-fake-")]

    assert fakes
    for arg in fakes:
        value = Path(arg.split("=", 1)[1])
        assert value.parent.name == "bin"
        assert value.suffix == ".bin"


def test_game_filter_disabled_uses_stub_port() -> None:
    """При выключенном игровом фильтре апстрим подставляет порт-заглушку 12."""
    spec = parse_bat(BUNDLE_NEW / "general.bat")
    tcp = next(a for a in spec.argv if a.startswith("--wf-tcp="))

    assert tcp.endswith(",12"), tcp
    assert ",," not in tcp, "пустая подстановка оставила двойную запятую"


def test_game_filter_ranges_are_substituted() -> None:
    spec = parse_bat(
        BUNDLE_NEW / "general.bat",
        game_filter_tcp="1024-65535",
        game_filter_udp="2048-4096",
    )
    tcp = next(a for a in spec.argv if a.startswith("--wf-tcp="))
    udp = next(a for a in spec.argv if a.startswith("--wf-udp="))

    assert tcp.endswith(",1024-65535"), tcp
    assert udp.endswith(",2048-4096"), udp


def test_sections_split_on_new() -> None:
    spec = parse_bat(BUNDLE_NEW / "general.bat")

    assert len(spec.sections) == spec.argv.count("--new") + 1
    assert all(section.args for section in spec.sections)
    assert "--new" not in [arg for section in spec.sections for arg in section.args]


def test_first_section_carries_kernel_filters() -> None:
    """Флаги уровня ядра (--wf-*) идут до первого --new."""
    spec = parse_bat(BUNDLE_NEW / "general.bat")
    head = spec.sections[0].args

    assert any(a.startswith("--wf-tcp=") for a in head)
    assert any(a.startswith("--wf-udp=") for a in head)


def test_section_describe_is_readable() -> None:
    spec = parse_bat(BUNDLE_NEW / "general.bat")
    described = [section.describe() for section in spec.sections]

    assert all(described)
    assert any("обход:" in text for text in described)


def test_split_sections_handles_empty_input() -> None:
    assert split_sections([]) == []


def test_service_binpath_quotes_exe_and_spaced_values() -> None:
    exe = Path(r"C:\zapret\bin\winws.exe")
    argv = ["--wf-tcp=80,443", r"--hostlist=C:\Program Files\list.txt", "--dpi-desync=fake"]

    binpath = to_service_binpath(exe, argv)

    assert binpath.startswith('"C:\\zapret\\bin\\winws.exe" ')
    assert '--hostlist="C:\\Program Files\\list.txt"' in binpath
    assert "--dpi-desync=fake" in binpath
    assert '"--dpi-desync=fake"' not in binpath, "значение без пробелов закавычивать не нужно"


def test_service_binpath_roundtrip_for_every_strategy() -> None:
    """Строка для sc create должна содержать все аргументы стратегии."""
    exe = BUNDLE_NEW / "bin" / "winws.exe"
    for path in NEW_STRATEGIES:
        spec = parse_bat(path)
        binpath = to_service_binpath(exe, spec.argv)
        assert binpath.count("--new") == spec.argv.count("--new")


def test_parse_rejects_file_without_winws(tmp_path: Path) -> None:
    bad = tmp_path / "notastrategy.bat"
    bad.write_text("@echo off\r\necho hello\r\n", encoding="utf-8")

    with pytest.raises(BatParseError):
        parse_bat(bad)


def test_cyrillic_named_strategy_parses() -> None:
    """В 1.6.1 есть стратегии с кириллицей в имени и комментариях."""
    path = BUNDLE_OLD / "general (МГТС).bat"
    spec = parse_bat(path)

    assert isinstance(spec, StrategySpec)
    assert spec.argv
