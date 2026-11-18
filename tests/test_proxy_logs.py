"""Журнал прокси для Telegram на экране логов — без ключа подключения."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import telegram

KEY = "ab" * 16


@pytest.mark.parametrize(
    "line",
    [
        f"tg://proxy?server=127.0.0.1&port=1443&secret=dd{KEY}",
        f"https://t.me/proxy?server=127.0.0.1&port=1443&secret={KEY}",
        f"secret: {KEY}",
        f"ee{KEY}676f6f676c652e636f6d",
    ],
)
def test_key_never_reaches_the_screen(line: str) -> None:
    """«Скопировать» на экране логов унесло бы ключ в чат вместе с вопросом о помощи."""
    shown = telegram.redact(line)

    assert KEY not in shown
    assert telegram.HIDDEN in shown


def test_ordinary_lines_stay_as_they_are() -> None:
    line = "stats: total=172 active=11 ws=0 cf=0 err=436 up=0.0B down=0.0B"

    assert telegram.redact(line) == line


def test_tail_reads_the_end_and_hides_the_key(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "proxy.log"
    lines = [f"line {i}" for i in range(50)] + [f"secret={KEY}"]
    log.write_text("\n".join(lines), encoding="utf-8")
    monkeypatch.setattr(telegram, "log_file", lambda: log)

    tail = telegram.log_tail(limit=3)

    assert tail[:2] == ["line 48", "line 49"]
    assert not re.search(KEY, tail[-1])
