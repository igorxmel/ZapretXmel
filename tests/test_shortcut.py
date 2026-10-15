"""Тесты ярлыка на рабочем столе.

Создание `.lnk` трогает систему, поэтому проверяется то, что проверить можно
без неё: путь к рабочему столу и устойчивость к его отсутствию. Сам ярлык
собирает PowerShell.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import paths, shortcut


def test_desktop_folder_exists() -> None:
    """Путь спрашивается у Windows: папка переносится в OneDrive и локализуется."""
    desktop = shortcut.desktop_dir()

    assert desktop.is_dir(), f"рабочий стол не найден: {desktop}"


def test_shortcut_path_is_on_the_desktop() -> None:
    assert shortcut.path().parent == shortcut.desktop_dir()
    assert shortcut.path().suffix == ".lnk"


def test_target_points_at_the_running_program() -> None:
    assert shortcut.target() == paths.executable()


def test_missing_shortcut_is_not_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: tmp_path)

    assert not shortcut.exists()
    assert shortcut.remove()


def test_retarget_does_nothing_without_a_shortcut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ярлык, которого человек не просил, создавать не надо."""
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: tmp_path)
    monkeypatch.setattr(
        shortcut, "create", lambda *_: pytest.fail("ярлыка нет — создавать нечего")
    )

    shortcut.retarget(tmp_path / "ZapretXmel.exe")
