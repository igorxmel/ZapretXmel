"""Тесты ярлыков: на рабочем столе и в меню «Пуск».

Создание `.lnk` трогает систему, поэтому проверяется то, что проверить можно
без неё: пути к папкам, устойчивость к их отсутствию и поведение после
переезда программы. Сам ярлык собирает PowerShell.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import paths, shortcut


@pytest.fixture
def places(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    """Подменяет обе системные папки на временные."""
    folders = {
        shortcut.DESKTOP: tmp_path / "Рабочий стол",
        shortcut.START_MENU: tmp_path / "Programs",
    }
    for folder in folders.values():
        folder.mkdir()

    monkeypatch.setattr(shortcut, "folder", lambda where=shortcut.DESKTOP: folders[where])
    return folders


def test_both_folders_exist() -> None:
    """Пути спрашиваются у Windows: папки переносятся и локализуются."""
    for where in (shortcut.DESKTOP, shortcut.START_MENU):
        assert shortcut.folder(where).is_dir(), f"папка не найдена: {where}"


def test_start_menu_is_the_folder_windows_search_reads() -> None:
    """Поиск в «Пуске» просматривает Programs — ярлык должен лечь туда."""
    assert shortcut.folder(shortcut.START_MENU).name == "Programs"


def test_shortcut_paths_differ_by_place() -> None:
    desktop = shortcut.path(shortcut.DESKTOP)
    start_menu = shortcut.path(shortcut.START_MENU)

    assert desktop != start_menu
    assert desktop.suffix == start_menu.suffix == ".lnk"


def test_target_points_at_the_running_program() -> None:
    assert shortcut.target() == paths.executable()


def test_missing_shortcut_is_not_an_error(places: dict[str, Path]) -> None:
    for where in places:
        assert not shortcut.exists(where)
        assert shortcut.remove(where)


def test_retarget_does_nothing_without_a_shortcut(
    places: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ярлык, которого человек не просил, создавать не надо."""
    monkeypatch.setattr(
        shortcut, "create", lambda *_, **__: pytest.fail("ярлыка нет — создавать нечего")
    )

    shortcut.retarget(Path("C:/Новое место/ZapretXmel.exe"))


def test_relocation_updates_the_start_menu_too(
    places: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """После переезда поиск Windows должен вести на новое место.

    Ярлык в «Пуске» указывает на файл, а файл переезжает вместе с папкой.
    Не переписать его — значит оставить в поиске кнопку, которая открывает
    пустоту.
    """
    for where in places:
        shortcut.path(where).write_text("старый ярлык", encoding="utf-8")

    rewritten: list[str] = []
    monkeypatch.setattr(
        shortcut,
        "create",
        lambda _executable=None, where=shortcut.DESKTOP: rewritten.append(where),
    )

    shortcut.retarget(Path("C:/Новое место/ZapretXmel.exe"))

    assert sorted(rewritten) == sorted(places), "переписать надо оба ярлыка"


def test_remove_all_names_what_it_removed(places: dict[str, Path]) -> None:
    """Забытый в «Пуске» ярлык обиднее всего: программы нет, а поиск её находит."""
    shortcut.path(shortcut.START_MENU).write_text("ярлык", encoding="utf-8")

    removed = shortcut.remove_all()

    assert removed == [shortcut.TITLES[shortcut.START_MENU]]
    assert not shortcut.exists(shortcut.START_MENU)
