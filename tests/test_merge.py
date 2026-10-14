"""Тесты сборки стратегии из частей нескольких.

Самое важное здесь — круговой разбор: собранный .bat обязан прочитаться
обратно ровно в те же аргументы. Иначе стратегия молча запустится не с тем,
что показано пользователю, и разбираться в этом будет уже негде.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import merge
from app.core.batfile import parse_bat
from app.core.merge import MergePlan, merge_kernel_flags, plan_from_winners

FIXTURES = Path(__file__).parent / "fixtures" / "bundle_1_10_3"


@pytest.fixture
def specs():
    return [
        parse_bat(FIXTURES / "general.bat", root=FIXTURES),
        parse_bat(FIXTURES / "general (ALT12).bat", root=FIXTURES),
    ]


# --- план ---------------------------------------------------------------


def test_plan_lists_sources_without_repeats() -> None:
    plan = plan_from_winners({"Discord": "ALT12", "YouTube": "general", "Google": "general"})

    assert plan.strategy_names == ["ALT12", "general"]


def test_plan_is_useless_when_one_strategy_wins_everything() -> None:
    plan = plan_from_winners({"Discord": "general", "YouTube": "general"})

    assert not plan.is_useful


def test_plan_is_useful_for_different_winners() -> None:
    assert plan_from_winners({"Discord": "ALT12", "YouTube": "general"}).is_useful


def test_empty_plan_is_useless() -> None:
    assert not MergePlan().is_useful


# --- флаги уровня ядра --------------------------------------------------


def test_kernel_ports_are_united(specs) -> None:
    """Порты обеих стратегий должны попасть в перехват, иначе часть трафика пройдёт мимо."""
    merged = merge_kernel_flags(specs)
    tcp = next(flag for flag in merged if flag.startswith("--wf-tcp="))
    ports = set(tcp.split("=", 1)[1].split(","))

    for spec in specs:
        original = next(f for f in spec.argv if f.startswith("--wf-tcp="))
        assert set(original.split("=", 1)[1].split(",")) <= ports


def test_kernel_ports_have_no_duplicates(specs) -> None:
    for flag in merge_kernel_flags(specs):
        ports = flag.split("=", 1)[1].split(",")
        assert len(ports) == len(set(ports))


# --- сборка -------------------------------------------------------------


def test_single_strategy_is_returned_as_is(specs) -> None:
    assert merge.merge([specs[0]]) == specs[0].argv


def test_empty_input_gives_nothing() -> None:
    assert merge.merge([]) == []


def test_merge_keeps_sections_of_both(specs) -> None:
    argv = merge.merge(specs)
    sections = argv.count("--new") + 1

    assert sections > max(len(spec.sections) for spec in specs)


def test_merge_moves_kernel_flags_to_the_front(specs) -> None:
    """Флаги уровня ядра действуют на всю команду и должны стоять до секций."""
    argv = merge.merge(specs)
    kernel_positions = [i for i, arg in enumerate(argv) if arg.startswith("--wf-")]
    first_new = argv.index("--new")

    assert kernel_positions
    assert max(kernel_positions) < first_new


def test_identical_sections_are_not_duplicated(specs) -> None:
    doubled = merge.merge([specs[0], specs[0]])

    assert doubled.count("--new") + 1 == len(specs[0].sections)


# --- запись и обратный разбор -------------------------------------------


def test_saved_strategy_parses_back_identically(specs, tmp_path: Path) -> None:
    """Главная проверка: что собрали, то и прочиталось."""
    (tmp_path / "bin").mkdir()
    plan = plan_from_winners({"Discord": specs[1].name, "YouTube": specs[0].name})
    argv = merge.merge(specs)

    path = merge.save(argv, plan, root=tmp_path)
    restored = parse_bat(path, root=tmp_path)

    assert restored.argv == argv


def test_saved_file_uses_windows_newlines(specs, tmp_path: Path) -> None:
    """Двойной возврат каретки рвёт склейку переносов и обнуляет аргументы."""
    (tmp_path / "bin").mkdir()
    plan = plan_from_winners({"Discord": specs[1].name, "YouTube": specs[0].name})

    path = merge.save(merge.merge(specs), plan, root=tmp_path)
    raw = path.read_bytes()

    assert b"\r\n" in raw
    assert b"\r\r\n" not in raw


def test_saved_file_records_its_origin(specs, tmp_path: Path) -> None:
    (tmp_path / "bin").mkdir()
    plan = plan_from_winners({"Discord": specs[1].name, "YouTube": specs[0].name})

    path = merge.save(merge.merge(specs), plan, root=tmp_path)
    text = path.read_text(encoding="utf-8")

    assert "собрана программой" in text
    assert specs[1].name in text


def test_merged_strategy_is_recognisable() -> None:
    assert merge.is_merged(merge.merged_name())
    assert not merge.is_merged("general (ALT12)")
