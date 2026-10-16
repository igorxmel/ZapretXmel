"""Тесты списка изменений, который читает сама программа.

Окно «что нового» показывается после обновления и обязано работать без
сети: её может не быть именно из-за тех блокировок, ради которых программу
и поставили.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import changelog, paths

TEXT = (
    "# Что менялось\n\n"
    "## 0.2.0\n\nНовое и прекрасное.\n\n"
    "## 0.1.16\n\n### Добавлено\n\n- журнал программы\n\n"
    "## 0.1.15\n\nстарое\n"
)


def test_section_is_taken_without_the_heading() -> None:
    assert changelog.section(TEXT, "0.1.16") == "### Добавлено\n\n- журнал программы"


def test_next_version_does_not_leak_in() -> None:
    assert changelog.section(TEXT, "0.2.0") == "Новое и прекрасное."


def test_unknown_version_gives_nothing() -> None:
    assert changelog.section(TEXT, "9.9.9") == ""


def test_packed_file_wins_over_the_source_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """В сборке список лежит рядом с картинками, в исходниках — в корне."""
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / changelog.FILENAME).write_text(TEXT, encoding="utf-8")

    monkeypatch.setattr(paths, "assets_dir", lambda: assets)
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path)

    assert changelog.file() == assets / changelog.FILENAME
    assert "журнал программы" in changelog.read("0.1.16")


def test_source_file_is_used_when_nothing_is_packed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / changelog.FILENAME).write_text(TEXT, encoding="utf-8")
    monkeypatch.setattr(paths, "assets_dir", lambda: tmp_path / "нет такой")
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path)

    assert changelog.read("0.2.0") == "Новое и прекрасное."


def test_missing_file_is_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "assets_dir", lambda: tmp_path / "нет")
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path / "тоже нет")

    assert changelog.read("0.1.16") == ""


def test_current_version_is_described() -> None:
    """Выпускать версию без раздела нельзя — окно откроется пустым."""
    from app import __version__

    assert changelog.read(__version__), f"нет раздела про {__version__}"
