"""Тесты режимов ipset.

Режим кодируется содержимым файла — проверяем, что мы читаем и пишем его так же,
как это делает service.bat, иначе консольное меню и GUI покажут разное.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import ipset
from app.core.ipset import NONE_MARKER, next_mode, status


@pytest.fixture
def lists_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ipset.paths, "core_lists", lambda: tmp_path)
    return tmp_path


def test_empty_file_means_any(lists_dir: Path) -> None:
    ipset.list_file().write_text("", encoding="utf-8")

    assert status() == "any"


def test_missing_file_means_any(lists_dir: Path) -> None:
    assert status() == "any"


def test_marker_means_none(lists_dir: Path) -> None:
    ipset.list_file().write_text(f"{NONE_MARKER}\n", encoding="utf-8")

    assert status() == "none"


def test_real_content_means_loaded(lists_dir: Path) -> None:
    ipset.list_file().write_text("1.1.1.0/24\n8.8.8.0/24\n", encoding="utf-8")

    assert status() == "loaded"


def test_switch_loaded_to_none_keeps_backup(lists_dir: Path) -> None:
    ipset.list_file().write_text("1.1.1.0/24\n", encoding="utf-8")

    ipset.set_mode("none")

    assert status() == "none"
    assert ipset.backup_file().read_text(encoding="utf-8").strip() == "1.1.1.0/24"


def test_switch_back_to_loaded_restores_backup(lists_dir: Path) -> None:
    ipset.list_file().write_text("1.1.1.0/24\n", encoding="utf-8")
    ipset.set_mode("none")
    ipset.set_mode("any")

    ipset.set_mode("loaded")

    assert status() == "loaded"
    assert "1.1.1.0/24" in ipset.list_file().read_text(encoding="utf-8")
    assert not ipset.backup_file().exists()


def test_switch_to_loaded_without_backup_fails(lists_dir: Path) -> None:
    ipset.list_file().write_text("", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        ipset.set_mode("loaded")


def test_switch_to_current_mode_is_noop(lists_dir: Path) -> None:
    ipset.list_file().write_text("1.1.1.0/24\n", encoding="utf-8")

    ipset.set_mode("loaded")

    assert not ipset.backup_file().exists(), "лишний бэкап при отсутствии изменений"


def test_mode_cycle_matches_upstream_menu() -> None:
    assert next_mode("loaded") == "none"
    assert next_mode("none") == "any"
    assert next_mode("any") == "loaded"


def test_real_bundle_backup_is_detected_as_loaded(lists_dir: Path) -> None:
    """В поставке 1.10.3 активный ipset-all.txt содержит маркер, а список лежит в .backup."""
    ipset.list_file().write_text(f"{NONE_MARKER}\n", encoding="utf-8")
    ipset.backup_file().write_text("1.1.1.0/24\n", encoding="utf-8")

    assert status() == "none"
    assert ipset.has_backup()
