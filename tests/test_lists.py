"""Тесты редактора пользовательских списков."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import lists
from app.core.lists import PLACEHOLDER_DOMAIN, UserList, is_valid_domain, is_valid_ip, read, write


@pytest.mark.parametrize(
    "value",
    ["youtube.com", "www.google.com", "i.ytimg.com", "xn--80ak6aa92e.com", "a.b.c.d.example"],
)
def test_valid_domains(value: str) -> None:
    assert is_valid_domain(value)


@pytest.mark.parametrize(
    "value",
    ["", "-bad.com", "bad-.com", "two..dots.com", "сайт пробел.com", "a" * 300],
)
def test_invalid_domains(value: str) -> None:
    assert not is_valid_domain(value)


@pytest.mark.parametrize(
    "value", ["1.1.1.1", "203.0.113.0/24", "10.0.0.0/8", "2606:4700::/32", "::1"]
)
def test_valid_ips(value: str) -> None:
    assert is_valid_ip(value)


@pytest.mark.parametrize("value", ["", "999.1.1.1", "1.1.1.1/33", "youtube.com", "1.1.1"])
def test_invalid_ips(value: str) -> None:
    assert not is_valid_ip(value)


@pytest.fixture
def domain_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> UserList:
    monkeypatch.setattr(lists.paths, "core_lists", lambda: tmp_path)
    return UserList(filename="list-general-user.txt", kind="domain", title="Тест", hint="")


def test_write_sorts_and_deduplicates(domain_list: UserList) -> None:
    count = write(domain_list, ["youtube.com", "discord.com", "YouTube.com", "a.com"])

    assert count == 3
    assert read(domain_list).entries == ["a.com", "discord.com", "youtube.com"]


def test_write_drops_invalid_entries(domain_list: UserList) -> None:
    write(domain_list, ["youtube.com", "-плохо-", "две..точки.com"])

    assert read(domain_list).entries == ["youtube.com"]


def test_empty_list_gets_placeholder(domain_list: UserList) -> None:
    """Пустой список ломает winws, поэтому апстрим всегда держит в нём заглушку."""
    write(domain_list, [])

    assert read(domain_list).entries == [PLACEHOLDER_DOMAIN]


def test_comments_are_preserved(domain_list: UserList) -> None:
    write(domain_list, ["youtube.com"], comments=["# мой список"])
    content = read(domain_list)

    assert content.comments == ["# мой список"]
    assert content.entries == ["youtube.com"]


def test_read_reports_invalid_lines(domain_list: UserList) -> None:
    domain_list.path.write_text("youtube.com\nсовсем не домен!\n", encoding="utf-8")
    content = read(domain_list)

    assert content.entries == ["youtube.com"]
    assert content.invalid == ["совсем не домен!"]


def test_read_missing_file_is_empty(domain_list: UserList) -> None:
    content = read(domain_list)

    assert content.entries == []
    assert content.invalid == []


def test_import_merges_without_losing_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target" / "lists"
    target.mkdir(parents=True)
    monkeypatch.setattr(lists.paths, "core_lists", lambda: target)

    user_list = next(ul for ul in lists.USER_LISTS if ul.filename == "list-general-user.txt")
    write(user_list, ["already.com"])

    source = tmp_path / "source"
    (source / "lists").mkdir(parents=True)
    (source / "lists" / "list-general-user.txt").write_text(
        f"# старый файл\nimported.com\n{PLACEHOLDER_DOMAIN}\n", encoding="utf-8"
    )

    imported = lists.import_from(source)

    assert imported["list-general-user.txt"] == 1
    assert read(user_list).entries == ["already.com", "imported.com"]


def test_import_finds_lists_in_bundle_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """В сборке 1.6.1 списки лежали прямо в корне, без каталога lists/."""
    target = tmp_path / "target" / "lists"
    target.mkdir(parents=True)
    monkeypatch.setattr(lists.paths, "core_lists", lambda: target)

    source = tmp_path / "old-zapret"
    source.mkdir()
    (source / "list-general-user.txt").write_text("fromroot.com\n", encoding="utf-8")

    imported = lists.import_from(source)

    assert imported["list-general-user.txt"] == 1


def test_ensure_user_lists_creates_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lists.paths, "core_lists", lambda: tmp_path)

    lists.ensure_user_lists()

    for user_list in lists.USER_LISTS:
        assert user_list.path.exists(), user_list.filename
        assert read(user_list).entries == [user_list.placeholder]
