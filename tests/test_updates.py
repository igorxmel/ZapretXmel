"""Тесты поиска обновлений.

Три источника с разными правилами: программа, ядро zapret и прокси для
Telegram. Главное свойство — молчаливость: GitHub может не ответить, а у
части провайдеров он и вовсе недоступен без обхода, и ругаться на это
посреди работы незачем.
"""

from __future__ import annotations

import pytest

from app.core import updates


class FakeRelease:
    def __init__(self, version: str):
        self.version = version
        self.tag = version


def test_unreachable_source_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Одна недоступная проверка не должна уносить с собой остальные."""

    def explode() -> None:
        raise OSError("GitHub недоступен")

    monkeypatch.setattr(updates, "check_app", explode)
    monkeypatch.setattr(updates, "check_core", lambda: None)
    monkeypatch.setattr(
        updates, "check_proxy", lambda: updates.Available(updates.PROXY, "1.0", "1.1", "telegram")
    )

    found = updates.check_all()

    assert [item.what for item in found] == [updates.PROXY]


def test_nothing_found_when_everything_is_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("check_app", "check_core", "check_proxy"):
        monkeypatch.setattr(updates, name, lambda: None)

    assert updates.check_all() == []


def test_core_update_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        updates.coreinfo,
        "describe",
        lambda: type("Info", (), {"present": True, "version": "1.10.3"})(),
    )
    monkeypatch.setattr(updates.github, "latest_release", lambda _repo: FakeRelease("1.11.0"))

    found = updates.check_core()

    assert found is not None
    assert found.latest == "1.11.0"
    assert found.section == "updates"


def test_found_update_carries_the_release(monkeypatch: pytest.MonkeyPatch) -> None:
    """Релиз едет вместе с находкой, иначе экран спросит GitHub второй раз.

    Полоса вверху окна сообщала о новой версии, человек шёл по ней в раздел
    обновлений — а кнопка «Обновить» не горела, пока он не нажмёт
    «Проверить» и не получит тот же самый ответ.
    """
    release = FakeRelease("1.11.0")
    monkeypatch.setattr(
        updates.coreinfo,
        "describe",
        lambda: type("Info", (), {"present": True, "version": "1.10.3"})(),
    )
    monkeypatch.setattr(updates.github, "latest_release", lambda _repo: release)

    found = updates.check_core()

    assert found is not None
    assert found.release is release


def test_missing_core_is_not_an_update(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ядра нет — это не «устарело», а «ещё не установлено»."""
    monkeypatch.setattr(
        updates.coreinfo, "describe", lambda: type("Info", (), {"present": False, "version": ""})()
    )

    assert updates.check_core() is None


def test_proxy_without_known_version_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Прокси, поставленный до того, как версия стала запоминаться.

    Предлагать обновление «с неизвестной на свежую» при каждом запуске хуже,
    чем не предложить его один раз.
    """
    monkeypatch.setattr(updates.telegram, "is_installed", lambda: True)
    monkeypatch.setattr(updates.telegram, "installed_version", lambda: "")
    monkeypatch.setattr(updates.telegram, "latest_release", lambda: FakeRelease("1.11.2"))

    assert updates.check_proxy() is None


def test_outdated_proxy_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updates.telegram, "is_installed", lambda: True)
    monkeypatch.setattr(updates.telegram, "installed_version", lambda: "1.10.0")
    monkeypatch.setattr(updates.telegram, "latest_release", lambda: FakeRelease("1.11.2"))

    found = updates.check_proxy()

    assert found is not None
    assert found.section == "telegram", "вести надо туда, где прокси и ставится"


def test_summary_names_everything_found() -> None:
    found = [
        updates.Available(updates.APP, "0.1.10", "0.1.11", "updates"),
        updates.Available(updates.CORE, "1.10.3", "1.11.0", "updates"),
    ]

    text = updates.summary(found)

    assert "0.1.11" in text and "1.11.0" in text


def test_summary_of_nothing_is_empty() -> None:
    assert updates.summary([]) == ""
