"""Установка через Scoop: обновляет её Scoop, а не встроенный механизм."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import paths
from app.core.updater import selfupdate


@pytest.mark.parametrize(
    ("exe", "scoop"),
    [
        (r"C:\Users\me\scoop\apps\zapretxmel\current\ZapretXmel.exe", True),
        (r"D:\Tools\Scoop\apps\zapretxmel\0.4.11\ZapretXmel.exe", True),
        (r"C:\Program Files\ZapretXmel\ZapretXmel.exe", False),
        (r"D:\apps\ZapretXmel.exe", False),
        (r"C:\Users\me\scoop\apps\other\current\ZapretXmel.exe", False),
    ],
)
def test_scoop_install_is_recognised(monkeypatch, exe: str, scoop: bool) -> None:
    monkeypatch.setattr(paths, "executable", lambda: Path(exe))

    assert paths.is_scoop() is scoop


def test_scoop_install_never_offers_a_self_update(monkeypatch) -> None:
    """Иначе Scoop считал бы, что стоит старая версия, и скачивал бы новую второй раз."""
    monkeypatch.setattr(paths, "is_scoop", lambda: True)

    def must_not_ask(*_a, **_k):
        raise AssertionError("GitHub спрашивать незачем")

    monkeypatch.setattr(selfupdate.github, "latest_release", must_not_ask)

    assert selfupdate.check() is None
