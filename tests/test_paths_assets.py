"""Картинки сборки живут не во временной папке: её стирают чистильщики, пока программа работает."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.core import paths


@pytest.fixture
def frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    bundle = tmp_path / "_MEI123"
    (bundle / "assets" / "icons").mkdir(parents=True)
    (bundle / "assets" / "icons" / "window-help.svg").write_text("<svg/>", encoding="utf-8")
    (bundle / "assets" / "logo.png").write_bytes(b"png")
    data = tmp_path / "data"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(paths, "data_dir", lambda: data)
    paths.assets_dir.cache_clear()
    yield bundle, data
    paths.assets_dir.cache_clear()


def test_assets_survive_cleanup_of_temp_folder(frozen: tuple[Path, Path]) -> None:
    bundle, data = frozen

    assets = paths.assets_dir()
    (bundle / "assets" / "icons" / "window-help.svg").unlink()

    assert assets == data / "assets"
    assert (assets / "icons" / "window-help.svg").read_text(encoding="utf-8") == "<svg/>"


def test_changed_asset_is_refreshed(frozen: tuple[Path, Path]) -> None:
    bundle, data = frozen
    (data / "assets").mkdir(parents=True)
    (data / "assets" / "logo.png").write_bytes(b"old")

    paths.assets_dir()

    assert (data / "assets" / "logo.png").read_bytes() == b"png"


def test_unwritable_data_falls_back_to_bundle(
    frozen: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, _ = frozen

    def refuse(*_args, **_kwargs):
        raise PermissionError("нет доступа")

    monkeypatch.setattr(paths.shutil, "copyfile", refuse)

    assert paths.assets_dir() == bundle / "assets"


def test_missing_icon_does_not_crash_painting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PyQt6.QtWidgets import QApplication

    from app.ui import frameless

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(paths, "assets_dir", lambda: tmp_path / "нет")

    assert not frameless.svg_renderer("window-help", "#fff").isValid()
    assert app is not None
