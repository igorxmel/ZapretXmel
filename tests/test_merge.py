"""Тесты сборки стратегии из частей нескольких.

Прежняя сборка склеивала секции подряд и выглядела рабочей: файл был верный, тесты
зелёные. Но winws берёт первую подходящую секцию, и вторая стратегия не срабатывала
никогда. Поэтому здесь главное — какая секция реально сработает для сервиса.

Папка с пробелом не случайна: программа часто лежит в `D:\\Program Files`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.core import merge
from app.core.batfile import parse_bat, split_sections
from app.core.merge import MergePlan, merge_kernel_flags, plan_from_winners, selector
from app.core.probe.autopick import Report, StrategyScore

FIXTURES = Path(__file__).parent / "fixtures" / "bundle_1_10_3"

LISTS = {
    "list-general.txt": "discord.com\ndiscord.gg\ndiscordapp.com\ncloudflare.com\n",
    "list-google.txt": "youtube.com\nytimg.com\ngooglevideo.com\ngstatic.com\n",
    "list-exclude.txt": "pass.example\n",
}
HOSTS = {
    "Discord": ["discord.com", "gateway.discord.gg"],
    "YouTube": ["www.youtube.com", "i.ytimg.com"],
    "Cloudflare": ["www.cloudflare.com"],
}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    bundle = tmp_path / "Program Files" / "ZapretXmel" / "core"
    shutil.copytree(FIXTURES, bundle)
    lists = bundle / "lists"
    lists.mkdir(exist_ok=True)
    for name, text in LISTS.items():
        (lists / name).write_text(text, encoding="utf-8")
    (bundle / "bin").mkdir(exist_ok=True)
    return bundle


@pytest.fixture
def general(root: Path):
    return parse_bat(root / "general.bat", root=root)


@pytest.fixture
def alt(root: Path):
    return parse_bat(root / "general (ALT12).bat", root=root)


def _first_match(sections, host: str, protocol: str = "tcp", port: int = 443):
    for section in sections:
        if merge.section_matches(section, host, protocol, port):
            return section
    raise AssertionError(f"{host}: ни одна секция не подошла")


def _built(plan: MergePlan, specs):
    composition = merge.compose(plan, specs, HOSTS)
    return composition, split_sections(composition.argv) if composition.argv else []


# --- план ---------------------------------------------------------------


def test_plan_lists_sources_without_repeats() -> None:
    plan = plan_from_winners({"Discord": "ALT12", "YouTube": "general", "Google": "general"})

    assert plan.strategy_names == ["ALT12", "general"]


def test_plan_is_useless_when_one_strategy_wins_everything() -> None:
    assert not plan_from_winners({"Discord": "general", "YouTube": "general"}).is_useful


def test_plan_is_useful_for_different_winners() -> None:
    assert plan_from_winners({"Discord": "ALT12", "YouTube": "general"}).is_useful


def test_empty_plan_is_useless() -> None:
    assert not MergePlan().is_useful


# --- какая секция сработает ----------------------------------------------


def test_each_service_gets_the_method_of_its_winner(general, alt) -> None:
    """Главная проверка. У прежней сборки всё доставалось первой стратегии."""
    plan = plan_from_winners({"Discord": alt.name, "YouTube": general.name})

    _, sections = _built(plan, [alt, general])

    discord = _first_match(sections, "discord.com")
    youtube = _first_match(sections, "www.youtube.com")
    assert discord.desync == _first_match(alt.sections, "discord.com").desync
    assert youtube.desync == _first_match(general.sections, "www.youtube.com").desync


def test_result_differs_from_both_sources(general, alt) -> None:
    plan = plan_from_winners({"Discord": alt.name, "YouTube": general.name})

    composition, _ = _built(plan, [alt, general])

    assert composition.argv
    assert composition.argv != general.argv
    assert composition.argv != alt.argv


def test_no_section_is_shadowed(general, alt) -> None:
    """Каждая секция сборки должна иметь шанс сработать."""
    plan = plan_from_winners({"Discord": alt.name, "YouTube": general.name})

    _, sections = _built(plan, [alt, general])

    filters = [selector(section) for section in sections]
    assert len(filters) == len(set(filters))


def test_build_is_about_as_long_as_its_sources(general, alt) -> None:
    """Склейка выходила почти вдвое длиннее и вылезала за предел .bat в 8191 знак."""
    plan = plan_from_winners({"Discord": alt.name, "YouTube": general.name})

    composition, sections = _built(plan, [alt, general])

    size = lambda argv: sum(len(arg) + 1 for arg in argv)  # noqa: E731
    assert len(sections) == len(general.sections)
    assert size(composition.argv) < 1.2 * max(size(general.argv), size(alt.argv))


def test_discord_voice_section_follows_the_discord_winner(general, alt) -> None:
    """Голос идёт на свои порты, и по адресам сайта эту секцию не найти."""
    sections = merge.rule_sections(general)

    found = merge.sections_for_service(sections, "Discord", HOSTS["Discord"])

    assert any("--filter-l7=discord,stun" in sections[index].args for index in found)


def test_shared_section_stays_with_the_base_and_is_reported(general, alt) -> None:
    """Discord и Cloudflare оба в list-general, а способ обхода там один."""
    plan = plan_from_winners(
        {"Discord": alt.name, "YouTube": general.name, "Cloudflare": general.name}
    )

    composition, _ = _built(plan, [alt, general])

    assert composition.base == general.name
    assert "Discord" in composition.conflicts


def test_nothing_to_swap_gives_no_strategy(general, alt) -> None:
    """Все сервисы в одной секции: сборка была бы копией основы."""
    shared = {"Первый": ["www.cloudflare.com"], "Второй": ["www.cloudflare.com"]}
    plan = plan_from_winners({"Первый": general.name, "Второй": alt.name})

    composition = merge.compose(plan, [general, alt], shared)

    assert composition.argv == []
    assert composition.conflicts


def test_excluded_host_does_not_match(general) -> None:
    assert not any(
        merge.section_matches(section, "pass.example", "tcp", 443)
        and any(arg.startswith("--hostlist=") for arg in section.args)
        for section in general.sections
    )


@pytest.mark.parametrize(
    ("value", "port", "listed"),
    [("80,443", 443, True), ("19294-19344,50000-50100", 50050, True), ("80,443", 8443, False)],
)
def test_port_lists(value: str, port: int, listed: bool) -> None:
    assert merge._port_listed(value, port) is listed


# --- флаги уровня ядра --------------------------------------------------


def test_kernel_ports_are_united(general, alt) -> None:
    """Порты обеих стратегий должны попасть в перехват, иначе часть трафика пройдёт мимо."""
    tcp = next(flag for flag in merge_kernel_flags([general, alt]) if flag.startswith("--wf-tcp="))
    ports = set(tcp.split("=", 1)[1].split(","))

    for spec in (general, alt):
        original = next(f for f in spec.argv if f.startswith("--wf-tcp="))
        assert set(original.split("=", 1)[1].split(",")) <= ports


def test_kernel_ports_have_no_duplicates(general, alt) -> None:
    for flag in merge_kernel_flags([general, alt]):
        ports = flag.split("=", 1)[1].split(",")
        assert len(ports) == len(set(ports))


def test_kernel_flags_stay_in_the_first_section(general, alt) -> None:
    plan = plan_from_winners({"Discord": alt.name, "YouTube": general.name})

    composition, _ = _built(plan, [alt, general])

    kernel = [i for i, arg in enumerate(composition.argv) if arg.startswith("--wf-")]
    assert kernel and max(kernel) < composition.argv.index("--new")
    first = split_sections(composition.argv)[0]
    assert selector(first), "первая секция без фильтра затенит все"


# --- запись и обратный разбор -------------------------------------------


def _saved(general, alt, root: Path) -> tuple[list[str], Path]:
    plan = plan_from_winners({"Discord": alt.name, "YouTube": general.name})
    argv = merge.compose(plan, [alt, general], HOSTS).argv
    return argv, merge.save(argv, plan, root=root)


def test_saved_strategy_parses_back_identically(general, alt, root: Path) -> None:
    """Что собрали, то и прочиталось. В том числе из папки с пробелом."""
    assert " " in str(root)

    argv, path = _saved(general, alt, root)

    assert parse_bat(path, root=root).argv == argv


def test_saved_file_uses_windows_newlines(general, alt, root: Path) -> None:
    """Двойной возврат каретки рвёт склейку переносов и обнуляет аргументы."""
    _, path = _saved(general, alt, root)
    raw = path.read_bytes()

    assert b"\r\n" in raw
    assert b"\r\r\n" not in raw


def test_saved_file_records_its_origin(general, alt, root: Path) -> None:
    _, path = _saved(general, alt, root)

    text = path.read_text(encoding="utf-8")

    assert "собрана программой" in text
    assert alt.name in text


def test_new_build_does_not_overwrite_the_previous(general, alt, root: Path) -> None:
    """Прошлая сборка может быть уже выбрана и работать."""
    _, first = _saved(general, alt, root)
    _, second = _saved(general, alt, root)

    assert first != second
    assert first.exists() and second.exists()
    assert merge.is_merged(first.stem) and merge.is_merged(second.stem)
    assert not merge.is_merged("general (ALT12)")


def test_saved_build_appears_in_the_strategy_list(general, alt, root: Path) -> None:
    from app.core import strategies

    _, path = _saved(general, alt, root)

    assert path.stem in [item.stem for item in strategies.discover(root)]


# --- оставлять ли сборку --------------------------------------------------


def _score(name: str, ok: int) -> StrategyScore:
    return StrategyScore(name=name, ok=ok, started=True)


def _report(*scores: StrategyScore, cancelled: bool = False) -> Report:
    return Report(
        mode="services", started_at="", finished_at="", checked=[], scores=list(scores),
        cancelled=cancelled,
    )


def test_better_build_is_kept() -> None:
    assert merge.is_improvement(_report(_score("a", 5), _score("сборка", 8)), "сборка")


def test_equal_build_is_not_kept() -> None:
    """Сборка мерится последней, и при равенстве побеждает исходная."""
    assert not merge.is_improvement(_report(_score("a", 5), _score("сборка", 5)), "сборка")


def test_worse_build_is_not_kept() -> None:
    assert not merge.is_improvement(_report(_score("a", 8), _score("сборка", 5)), "сборка")


def test_cancelled_measurement_proves_nothing() -> None:
    report = _report(_score("a", 5), _score("сборка", 8), cancelled=True)

    assert not merge.is_improvement(report, "сборка")
