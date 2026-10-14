"""Тесты управления прокси для Telegram."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import telegram
from app.core.telegram import ProxyState, ensure_config, generate_secret, read_config


@pytest.fixture
def proxy_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(telegram, "home", lambda: tmp_path)
    return tmp_path


def test_secret_is_32_hex_characters() -> None:
    """Формат задан самим прокси: 16 случайных байт в шестнадцатеричном виде."""
    secret = generate_secret()

    assert len(secret) == 32
    assert all(char in "0123456789abcdef" for char in secret)


def test_secrets_are_not_repeated() -> None:
    assert generate_secret() != generate_secret()


def test_config_is_created_with_defaults(proxy_home: Path) -> None:
    config = ensure_config()

    assert config["host"] == telegram.DEFAULT_HOST
    assert config["port"] == telegram.DEFAULT_PORT
    assert len(config["secret"]) == 32
    assert config["check_updates"] is False, "обновлениями занимаемся мы"


def test_config_lands_in_portable_folder(proxy_home: Path) -> None:
    """Папка рядом с exe уводит настройки из %APPDATA% и не трогает чужую установку."""
    ensure_config()

    assert telegram.config_file() == proxy_home / "TgWsProxy_data" / "config.json"
    assert telegram.config_file().exists()


def test_existing_secret_survives(proxy_home: Path) -> None:
    """Секрет прописан в настройках Telegram — менять его при перезапуске нельзя."""
    first = ensure_config()["secret"]

    second = ensure_config()["secret"]

    assert first == second


def test_port_change_keeps_secret(proxy_home: Path) -> None:
    original = ensure_config()["secret"]

    changed = ensure_config(port=1444)

    assert changed["port"] == 1444
    assert changed["secret"] == original


def test_foreign_keys_are_preserved(proxy_home: Path) -> None:
    """Прокси хранит в том же файле свои настройки — затирать их нельзя."""
    telegram.write_config({"secret": "a" * 32, "buf_kb": 512, "language": "ru"})

    config = ensure_config()

    assert config["buf_kb"] == 512
    assert config["language"] == "ru"


def test_broken_config_does_not_crash(proxy_home: Path) -> None:
    telegram.data_dir().mkdir(parents=True)
    telegram.config_file().write_text("{ это не json", encoding="utf-8")

    assert read_config() == {}
    assert len(ensure_config()["secret"]) == 32


def test_config_written_as_valid_json(proxy_home: Path) -> None:
    ensure_config()

    data = json.loads(telegram.config_file().read_text(encoding="utf-8"))

    assert isinstance(data, dict)


def test_link_matches_telegram_format() -> None:
    state = ProxyState(installed=True, running=True, host="127.0.0.1", port=1443, secret="ab" * 16)

    assert state.link == (
        "tg://proxy?server=127.0.0.1&port=1443&secret=" + "ab" * 16
    )


def test_no_link_without_secret() -> None:
    assert ProxyState(installed=True, running=True, secret="").link == ""


@pytest.mark.parametrize(
    ("installed", "running", "expected"),
    [
        (False, False, "не установлен"),
        (True, False, "остановлен"),
        (True, True, "работает"),
    ],
)
def test_state_labels(installed: bool, running: bool, expected: str) -> None:
    assert ProxyState(installed=installed, running=running).label == expected


def test_not_installed_until_executable_appears(proxy_home: Path) -> None:
    assert not telegram.is_installed()

    telegram.executable().parent.mkdir(parents=True, exist_ok=True)
    telegram.executable().write_bytes(b"")

    assert telegram.is_installed()
