"""Сайта проекта больше нет, а публичные тексты описывают программу, а не агитируют.

Правило и причина — в AGENTS.md, раздел «Публичные тексты». Проверка нужна потому, что
старая ссылка или лозунг возвращаются незаметно: достаточно скопировать абзац из истории.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ("README.md", "FAQ.md", "SECURITY.md", "CONTRIBUTING.md", "THIRD-PARTY.md")


def _sources() -> list[Path]:
    return [*(ROOT / name for name in DOCUMENTS), *(ROOT / "app").rglob("*.py")]


@pytest.mark.parametrize(
    "phrase",
    ["github.io/ZapretXmel", "Свободный интернет", "Обход блокировок в одном окне"],
)
def test_phrase_is_gone(phrase: str) -> None:
    offenders = [path.name for path in _sources() if phrase in path.read_text(encoding="utf-8")]

    assert offenders == []


def test_readers_are_told_there_is_no_site() -> None:
    """Иначе подделка под официальный сайт выглядела бы правдоподобно."""
    for name in ("README.md", "SECURITY.md"):
        text = (ROOT / name).read_text(encoding="utf-8")

        assert "подделка" in text and "не будет" in text


def test_site_folder_is_gone() -> None:
    assert not (ROOT / "docs").exists()


def test_title_bar_has_only_github() -> None:
    from app.ui.frameless import LINKS

    assert LINKS == (("GITHUB", "https://github.com/igorxmel/ZapretXmel"),)


def test_readme_pictures_exist() -> None:
    """Снимки лежали в папке сайта и уехали оттуда: битая картинка сама не напомнит."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pictures = [part.split('"')[0] for part in readme.split('="media/')[1:]]

    assert pictures
    for name in pictures:
        assert (ROOT / "media" / name).is_file(), name
