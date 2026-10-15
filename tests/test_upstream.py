"""Тесты сверки с апстримом.

Главное свойство: изменения должны попадать в правильную корзину. Новая
стратегия подхватится сама, новый флаг winws требует внимания, а исчезнувший
файл — ломающее, потому что на него могли ссылаться настройки.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import upstream
from app.core.upstream import Change, Diff, Fingerprint, collect_flags, compare, render_report

FIXTURES = Path(__file__).parent / "fixtures"
BUNDLE_NEW = FIXTURES / "bundle_1_10_3"
BUNDLE_OLD = FIXTURES / "bundle_1_6_1"


# --- отпечаток ----------------------------------------------------------


def test_fingerprint_sees_strategies_and_flags() -> None:
    fingerprint = upstream.build(BUNDLE_NEW)

    assert len(fingerprint.strategies) == 22
    assert "--dpi-desync" in fingerprint.winws_flags
    assert "--wf-tcp" in fingerprint.winws_flags


def test_fingerprint_reads_service_menu_and_labels() -> None:
    fingerprint = upstream.build(BUNDLE_NEW)

    assert any("Install Service" in item for item in fingerprint.service_menu)
    assert "service_install" in fingerprint.service_labels
    assert "ipset_update" in fingerprint.service_labels


def test_fingerprint_reads_target_keys() -> None:
    fingerprint = upstream.build(BUNDLE_NEW)

    assert "DiscordMain" in fingerprint.target_keys
    assert "YouTubeWeb" in fingerprint.target_keys


def test_fingerprint_hashes_every_file() -> None:
    fingerprint = upstream.build(BUNDLE_NEW)

    assert "service.bat" in fingerprint.files
    assert all(len(digest) == 64 for digest in fingerprint.files.values())


def test_user_lists_stay_out_of_the_fingerprint(tmp_path: Path) -> None:
    """Файлы пользователя не принадлежат апстриму и сверку волновать не должны.

    Снимок снимается с рабочей установки, где они есть, а сверяется со свежим
    релизом, где их нет и быть не может. Пока они попадали в отпечаток, каждая
    сверка объявляла их пропажу ломающим изменением.
    """
    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "list-general.txt").write_text("youtube.com\n", encoding="utf-8")
    (lists / "list-general-user.txt").write_text("example.com\n", encoding="utf-8")

    fingerprint = upstream.build(tmp_path)

    assert fingerprint.lists == ["list-general.txt"]
    assert not any(name.endswith("-user.txt") for name in fingerprint.files)


def test_flags_are_collected_from_all_strategies() -> None:
    flags = collect_flags(BUNDLE_NEW)

    assert flags == sorted(set(flags)), "флаги должны быть без повторов и отсортированы"
    assert all(flag.startswith("--") for flag in flags)


def test_empty_directory_gives_empty_fingerprint(tmp_path: Path) -> None:
    fingerprint = upstream.build(tmp_path)

    assert fingerprint.strategies == []
    assert fingerprint.service_labels == []


# --- раскладка изменений ------------------------------------------------


def test_new_strategy_is_picked_up_automatically() -> None:
    old = Fingerprint(strategies=["general.bat"])
    new = Fingerprint(strategies=["general.bat", "general (ALT99).bat"])

    diff = compare(old, new)

    assert not diff.needs_work
    assert any("general (ALT99).bat" in change.added for change in diff.automatic)


def test_new_flag_requires_attention() -> None:
    """Незнакомый флаг означает, что апстрим научился новому."""
    diff = compare(
        Fingerprint(winws_flags=["--wf-tcp"]),
        Fingerprint(winws_flags=["--wf-tcp", "--new-trick"]),
    )

    assert diff.needs_work
    assert any("--new-trick" in change.added for change in diff.attention)


def test_new_menu_item_requires_attention() -> None:
    """Пункт меню — это возможность, которой у интерфейса нет."""
    diff = compare(
        Fingerprint(service_menu=["Install Service"]),
        Fingerprint(service_menu=["Install Service", "Do Something New"]),
    )

    assert diff.needs_work
    assert any("Do Something New" in change.added for change in diff.attention)


def test_vanished_strategy_is_breaking() -> None:
    """На исчезнувшую стратегию могут ссылаться настройки и реестр."""
    diff = compare(Fingerprint(strategies=["a.bat", "b.bat"]), Fingerprint(strategies=["a.bat"]))

    assert diff.needs_work
    assert any("b.bat" in change.removed for change in diff.breaking)


def test_vanished_label_is_breaking() -> None:
    diff = compare(
        Fingerprint(service_labels=["service_install"]), Fingerprint(service_labels=[])
    )

    assert any("service_install" in change.removed for change in diff.breaking)


def test_identical_fingerprints_give_nothing() -> None:
    same = Fingerprint(strategies=["general.bat"], winws_flags=["--wf-tcp"])

    diff = compare(same, same)

    assert diff.is_empty
    assert not diff.needs_work


def test_real_bundles_differ_as_expected() -> None:
    """Между 1.6.1 и 1.10.3 апстрим добавил игровой фильтр, ipset и фейки."""
    diff = compare(upstream.build(BUNDLE_OLD), upstream.build(BUNDLE_NEW))

    assert diff.needs_work
    attention = {item for change in diff.attention for item in change.added}
    assert "--dpi-desync-fake-discord" in attention
    assert any("Game Filter" in item for item in attention)
    assert any("IPSet" in item for item in attention)


# --- отчёт --------------------------------------------------------------


def test_report_mentions_versions() -> None:
    text = render_report(Diff(old_version="1.6.1", new_version="1.10.3"))

    assert "1.6.1" in text
    assert "1.10.3" in text


def test_report_says_when_nothing_changed() -> None:
    assert "Расхождений нет" in render_report(Diff())


def test_report_puts_breaking_first() -> None:
    diff = Diff(
        attention=[Change(what="Флаги winws", added=["--new"])],
        breaking=[Change(what="Стратегии — исчезли", removed=["old.bat"])],
    )

    text = render_report(diff)

    assert text.index("Ломающее") < text.index("Требует внимания")


def test_report_lists_ideas_from_other_guis() -> None:
    diff = Diff(ideas={"someone/zapret-gui": "2.0 от 01.01.2026"})

    text = render_report(diff)

    assert "Идеи со стороны" in text
    assert "someone/zapret-gui" in text


# --- хранение -----------------------------------------------------------


@pytest.fixture
def upstream_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(upstream.paths, "upstream_dir", lambda: tmp_path)
    return tmp_path


def test_snapshot_survives_saving_and_loading(upstream_dir: Path) -> None:
    original = upstream.build(BUNDLE_NEW)

    upstream.save_snapshot(original)
    restored = upstream.load_snapshot()

    assert restored is not None
    assert restored.version == original.version
    assert restored.strategies == original.strategies
    assert restored.winws_flags == original.winws_flags


def test_missing_snapshot_is_not_an_error(upstream_dir: Path) -> None:
    assert upstream.load_snapshot() is None


def test_broken_snapshot_is_not_an_error(upstream_dir: Path) -> None:
    upstream.snapshot_file().write_text("{ не json", encoding="utf-8")

    assert upstream.load_snapshot() is None


def test_sources_fall_back_to_defaults(upstream_dir: Path) -> None:
    sources = upstream.load_sources()

    assert sources["core"] == "Flowseal/zapret-discord-youtube"
    assert sources["guis"]


def test_custom_sources_extend_defaults(upstream_dir: Path) -> None:
    upstream.save_sources({"guis": ["someone/fork"]})

    sources = upstream.load_sources()

    assert sources["guis"] == ["someone/fork"]
    assert sources["core"], "ядро должно остаться из значений по умолчанию"
