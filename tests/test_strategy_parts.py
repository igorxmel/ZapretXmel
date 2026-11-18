"""Экран стратегий без стены текста: имя по частям, цвет по проценту, секции по частям."""

from __future__ import annotations

from app.core.batfile import Section
from app.ui.strategy_parts import rate_colour, split_name
from app.ui.theme.tokens import COLORS


def test_common_prefix_is_split_from_what_differs() -> None:
    """Двадцать две строки «general (ALTn)» читались как одна."""
    assert split_name("general (ALT13)") == ("general", "ALT13")
    assert split_name("general (FAKE TLS AUTO ALT2)") == ("general", "FAKE TLS AUTO ALT2")
    assert split_name("моя стратегия") == ("", "моя стратегия")


def test_colour_tells_how_reliable_it_is() -> None:
    assert rate_colour(96) == COLORS["success"]
    assert rate_colour(76) == COLORS["warning"]
    assert rate_colour(40) == COLORS["danger"]


def test_section_is_taken_apart_for_the_badges() -> None:
    section = Section(
        [
            "--filter-tcp=80,443",
            "--hostlist=C:\\zapret\\lists\\list-general.txt",
            '--ipset="C:\\zapret\\lists\\ipset-all.txt"',
            "--dpi-desync=fake,hostfakesplit",
        ]
    )

    assert section.protocols == [("TCP", "80,443")]
    assert section.methods == ["fake", "hostfakesplit"]
    assert section.list_names == ["list-general", "ipset-all"]
