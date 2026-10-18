"""Тесты истории разборов нейросетью.

Разбор — не одноразовая справка: человек спрашивает, пробует совет и
спрашивает снова. Без истории прошлый ответ исчезает вместе с окном.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import paths
from app.core.diagnostics import aihistory
from app.core.diagnostics.ai import Analysis


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path)
    paths.reset_cache()
    yield tmp_path
    paths.reset_cache()


def analysis(verdict: str = "Режет TLS") -> Analysis:
    return Analysis(
        verdict=verdict,
        cause="Провайдер смотрит на имя сайта",
        steps=["Включить general (ALT)"],
        confidence="высокая",
        provider="OpenRouter",
        model="deepseek/deepseek-chat",
    )


def test_missing_history_is_not_an_error(home: Path) -> None:
    assert aihistory.load() == []


def test_entries_come_back_freshest_first(home: Path) -> None:
    aihistory.remember(analysis("первый"), "Discord молчит")
    aihistory.remember(analysis("второй"), "YouTube тормозит")

    entries = aihistory.load()

    assert [item.verdict for item in entries] == ["второй", "первый"]


def test_history_does_not_grow_forever(home: Path) -> None:
    """Советы устаревают вместе с правилами провайдера, хранить всё незачем."""
    for number in range(aihistory.LIMIT + 5):
        aihistory.remember(analysis(f"разбор {number}"), "проблема")

    assert len(aihistory.load()) == aihistory.LIMIT


def test_broken_file_reads_as_empty(home: Path) -> None:
    """Битый файл не должен мешать открыть окно."""
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    aihistory.file().write_text("{не json", encoding="utf-8")

    assert aihistory.load() == []


def test_title_says_when_and_about_what(home: Path) -> None:
    aihistory.remember(analysis(), "Discord не подключается")

    entry = aihistory.load()[0]

    assert "Discord не подключается" in entry.title
