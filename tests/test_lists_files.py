"""Обмен списками через файлы: «Добавить из файла…» и «Сохранить в файл…»."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from app.core import lists


def test_links_and_junk_become_clean_domains() -> None:
    """Списки ходят по чатам ссылками, с комментариями и звёздочками."""
    text = (
        "# мои сайты\n"
        "https://Example.com/watch?v=1\n"
        "*.cdn.example.org\n"
        "example.com\n"
        "rutracker.org  # трекер\n"
        "\n"
        f"{lists.PLACEHOLDER_DOMAIN}\n"
        "не домен\n"
    )

    good, bad = lists.parse_import(text, "domain")

    assert good == ["Example.com", "cdn.example.org", "rutracker.org"]
    assert bad == ["не домен"]


def test_addresses_are_checked_as_addresses() -> None:
    good, bad = lists.parse_import("10.0.0.0/8\n1.2.3.4\n300.1.1.1\n", "ip")

    assert good == ["10.0.0.0/8", "1.2.3.4"]
    assert bad == ["300.1.1.1"]


def test_export_drops_the_placeholder() -> None:
    assert lists.export_text(["a.com", lists.PLACEHOLDER_DOMAIN], "domain") == "a.com\n"
    assert lists.export_text([lists.PLACEHOLDER_DOMAIN], "domain") == ""


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.core import paths
    from app.core.config import Settings
    from app.ui.controller import Controller
    from app.ui.views.lists import ListsView

    (tmp_path / "lists").mkdir()
    monkeypatch.setattr(paths, "core_lists", lambda: tmp_path / "lists")
    made = ListsView(Controller(Settings()))
    made.reload()
    return made


def test_file_is_added_to_the_editor_not_saved(view, tmp_path, monkeypatch) -> None:
    """Импорт добавляет к своим, а не заменяет их, и на диск сам не пишет."""
    from app.ui.views import lists as screen

    source = tmp_path / "from-chat.txt"
    source.write_text("https://new.example/\nmine.example\n", encoding="utf-8")
    view._editor.setPlainText("mine.example")
    monkeypatch.setattr(
        screen.QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), "")
    )
    on_disk = lists.read(view._current).entries

    view._load_file()

    assert view._editor.toPlainText().splitlines() == ["mine.example", "new.example"]
    assert lists.read(view._current).entries == on_disk
    assert "1" in view._status.text()


def test_export_writes_what_is_in_the_editor(view, tmp_path, monkeypatch) -> None:
    from app.ui.views import lists as screen

    target = tmp_path / "out.txt"
    view._editor.setPlainText("b.example\nне домен\na.example")
    monkeypatch.setattr(
        screen.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "")
    )

    view._export_file()

    assert target.read_text(encoding="utf-8") == "b.example\na.example\n"
