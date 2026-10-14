"""Тесты выбора места установки.

Важны две вещи: указатель на папку читается без ошибок в любом состоянии
(нет файла, мусор внутри, исчезнувший диск), и переезд не теряет данные —
если на новом месте уже есть такая же часть установки, старая остаётся
лежать, а не перетирает её.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import location, paths


@pytest.fixture
def fake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Подменяет корень приложения, чтобы не трогать настоящий location.txt."""
    root = tmp_path / "app"
    root.mkdir()
    monkeypatch.setattr(paths, "app_root", lambda: root)
    paths.reset_cache()
    yield root
    paths.reset_cache()


def test_without_pointer_everything_lies_next_to_the_program(fake_root: Path) -> None:
    assert paths.install_root() == fake_root
    assert paths.is_portable()
    assert paths.core_dir() == fake_root / "core"


def test_pointer_moves_core_and_data(fake_root: Path, tmp_path: Path) -> None:
    target = tmp_path / "chosen"

    paths.set_install_root(target)

    assert paths.install_root() == target.resolve()
    assert paths.core_dir() == target.resolve() / "core"
    assert paths.data_dir() == target.resolve() / "data"
    assert not paths.is_portable()


def test_clearing_the_pointer_returns_portable_mode(fake_root: Path, tmp_path: Path) -> None:
    paths.set_install_root(tmp_path / "chosen")

    paths.set_install_root(None)

    assert paths.install_root() == fake_root
    assert not paths.location_file().exists()


def test_broken_pointer_falls_back_to_portable(fake_root: Path) -> None:
    """Мусор в указателе не должен ронять программу на каждом обращении к файлу."""
    paths.location_file().write_text("   ", encoding="utf-8")
    paths.reset_cache()

    assert paths.install_root() == fake_root


def test_pointer_to_a_vanished_drive_falls_back(fake_root: Path) -> None:
    """Путь на флешке переживает её извлечение: ставим заново рядом с программой."""
    paths.location_file().write_text(r"Q:\ZapretXmel", encoding="utf-8")
    paths.reset_cache()

    assert paths.install_root() == fake_root


def test_relative_pointer_is_ignored(fake_root: Path) -> None:
    paths.location_file().write_text("core", encoding="utf-8")
    paths.reset_cache()

    assert paths.install_root() == fake_root


# --- проверка выбранной папки -------------------------------------------


def test_current_folder_is_refused(fake_root: Path) -> None:
    assert location.check_target(fake_root) != ""


def test_folder_inside_the_installation_is_refused(fake_root: Path) -> None:
    (fake_root / "core").mkdir()

    assert location.check_target(fake_root / "core" / "deeper") != ""


def test_parent_of_the_installation_is_refused(fake_root: Path, tmp_path: Path) -> None:
    paths.set_install_root(tmp_path / "chosen" / "inner")

    assert location.check_target(tmp_path / "chosen") != ""


def test_relative_path_is_refused(fake_root: Path) -> None:
    assert location.check_target(Path("ZapretXmel")) != ""


def test_missing_drive_is_refused(fake_root: Path) -> None:
    assert "Q:" in location.check_target(Path(r"Q:\ZapretXmel"))


def test_file_instead_of_folder_is_refused(fake_root: Path, tmp_path: Path) -> None:
    occupied = tmp_path / "occupied"
    occupied.write_text("", encoding="utf-8")

    assert location.check_target(occupied) != ""


def test_empty_folder_is_accepted(fake_root: Path, tmp_path: Path) -> None:
    assert location.check_target(tmp_path / "chosen") == ""


def test_check_leaves_no_probe_file(fake_root: Path, tmp_path: Path) -> None:
    target = tmp_path / "chosen"

    location.check_target(target)

    assert list(target.iterdir()) == []


# --- переезд ------------------------------------------------------------


def test_relocation_moves_installed_parts(fake_root: Path, tmp_path: Path) -> None:
    (fake_root / "core" / "bin").mkdir(parents=True)
    (fake_root / "core" / "bin" / "winws.exe").write_text("exe", encoding="utf-8")
    (fake_root / "data").mkdir()
    (fake_root / "data" / "config.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "chosen"

    result = location.relocate(target)

    assert sorted(result.moved) == ["core", "data"]
    assert (target / "core" / "bin" / "winws.exe").read_text(encoding="utf-8") == "exe"
    assert not (fake_root / "core").exists()
    assert paths.core_dir() == target.resolve() / "core"


def test_relocation_keeps_what_is_already_there(fake_root: Path, tmp_path: Path) -> None:
    """Перетирать чужое ядро нельзя — обе копии должны уцелеть."""
    (fake_root / "core").mkdir()
    (fake_root / "core" / "mine.txt").write_text("мой", encoding="utf-8")
    target = tmp_path / "chosen"
    (target / "core").mkdir(parents=True)
    (target / "core" / "theirs.txt").write_text("чужой", encoding="utf-8")

    result = location.relocate(target)

    assert result.kept == ["core"]
    assert (target / "core" / "theirs.txt").exists()
    assert (fake_root / "core" / "mine.txt").exists(), "старую копию удалять нельзя"


def test_relocation_back_to_the_program_folder_removes_the_pointer(
    fake_root: Path, tmp_path: Path
) -> None:
    target = tmp_path / "chosen"
    paths.set_install_root(target)
    (target / "data").mkdir(parents=True)

    location.relocate(fake_root)

    assert paths.is_portable()
    assert not paths.location_file().exists()
    assert (fake_root / "data").exists()


def test_relocation_refuses_an_unsuitable_folder(fake_root: Path) -> None:
    with pytest.raises(ValueError, match="текущее место"):
        location.relocate(fake_root)


def test_relocation_creates_data_folders(fake_root: Path, tmp_path: Path) -> None:
    location.relocate(tmp_path / "chosen")

    assert paths.logs_dir().is_dir()
    assert paths.downloads_dir().is_dir()


def test_installed_size_counts_only_installed_parts(fake_root: Path) -> None:
    (fake_root / "core").mkdir()
    (fake_root / "core" / "big.bin").write_bytes(b"0" * (3 * 1024 * 1024))
    (fake_root / "ignored.bin").write_bytes(b"0" * (5 * 1024 * 1024))

    assert location.installed_size_mb() == 3


def test_free_space_is_measured_for_a_folder_that_does_not_exist_yet(
    fake_root: Path, tmp_path: Path
) -> None:
    assert location.free_space_mb(tmp_path / "chosen" / "deeper") > 0
