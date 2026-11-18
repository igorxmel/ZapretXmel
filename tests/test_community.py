"""Каталог списков сообщества: ветка community-lists этого же репозитория."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests
from PyQt6.QtWidgets import QApplication

from app.core import community, lists

INDEX = {
    "version": 1,
    "lists": [
        {
            "id": "games",
            "title": "Игры",
            "description": "Лаунчеры",
            "author": "someone",
            "kind": "domain",
            "file": "lists/games.txt",
        },
        {
            "id": "banks",
            "title": "Банки",
            "description": "Не трогать",
            "author": "other",
            "kind": "exclude",
            "file": "lists/banks.txt",
        },
        {"id": "broken", "title": "без полей"},
        {
            "id": "evil",
            "title": "Чужой путь",
            "description": "",
            "author": "x",
            "kind": "domain",
            "file": "https://evil.example/x.txt",
        },
        {
            "id": "ips",
            "title": "Адреса",
            "description": "",
            "author": "x",
            "kind": "ip",
            "file": "lists/ips.txt",
        },
    ],
}


class _Answer:
    def __init__(self, payload=None, text: str = "", status: int = 200):
        self._payload, self.text, self.status_code = payload, text, status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        if self._payload is None:
            raise ValueError("не json")
        return self._payload


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []
    files = {
        "index.json": _Answer(INDEX),
        "lists/games.txt": _Answer(
            text="# лаунчеры\nhttps://launcher.example/\ngame.example\nне домен\n"
        ),
    }

    def get(url, **_):
        path = url.removeprefix(community.BASE_URL + "/")
        asked.append(path)
        return files.get(path, _Answer(status=404))

    monkeypatch.setattr(community.requests, "get", get)
    return asked


def test_only_complete_entries_from_this_repo(server) -> None:
    """Неполные записи, чужие адреса файлов и неизвестные виды пропускаются."""
    entries = community.catalog()

    assert [entry.id for entry in entries] == ["games", "banks"]
    assert entries[0].target.filename == "list-general-user.txt"
    assert entries[1].target.filename == "list-exclude-user.txt"


def test_list_goes_through_the_same_check_as_a_file(server) -> None:
    entry = community.catalog()[0]

    good, bad = community.fetch(entry)

    assert good == ["launcher.example", "game.example"]
    assert bad == ["не домен"]


def test_no_network_is_a_plain_message(monkeypatch) -> None:
    def broken(*_a, **_k):
        raise requests.ConnectionError("10054")

    monkeypatch.setattr(community.requests, "get", broken)

    with pytest.raises(community.CatalogError, match="соединение с GitHub оборвалось"):
        community.catalog()


def test_reads_only_from_the_project_branch() -> None:
    assert community.BASE_URL.startswith("https://raw.githubusercontent.com/igorxmel/ZapretXmel/")
    assert community.BASE_URL.endswith("/community-lists")


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_chosen_list_lands_in_the_right_editor(app, server, tmp_path: Path, monkeypatch) -> None:
    from app.core import paths
    from app.core.config import Settings
    from app.ui.controller import Controller
    from app.ui.views.lists import ListsView

    (tmp_path / "lists").mkdir()
    monkeypatch.setattr(paths, "core_lists", lambda: tmp_path / "lists")
    view = ListsView(Controller(Settings()))
    view.reload()
    banks = community.catalog()[1]

    view._add_entry(banks, (["bank.example"], []))

    assert view._current.filename == "list-exclude-user.txt"
    assert "bank.example" in view._editor.toPlainText()
    assert lists.read(view._current).entries != ["bank.example"], "на диск само не пишет"
