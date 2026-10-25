"""Ресурс версии для .exe.

Проверяется на том, на чём сборка падает молча: файл должен разбираться самим
PyInstaller, иначе ошибка вылезет только на чистой сборочной машине при выпуске.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def build_release():
    script = ROOT / "tools" / "build_release.py"
    spec = importlib.util.spec_from_file_location("build_release", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_release"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.1.51", (0, 1, 51, 0)),
        ("1.9.9d", (1, 9, 9, 0)),  # правка апстрима поверх версии
        ("1.1.0-rc.1", (1, 1, 0, 0)),  # пре-релиз
        ("2", (2, 0, 0, 0)),
    ],
)
def test_version_numbers_fit_the_four_slots_windows_wants(build_release, version, expected) -> None:
    assert build_release.version_numbers(version) == expected


def test_resource_is_parsed_by_pyinstaller_itself(build_release, tmp_path: Path) -> None:
    from PyInstaller.utils.win32.versioninfo import load_version_info_from_text_file

    path = tmp_path / "version_info.txt"
    path.write_text(build_release.version_resource("0.1.51"), encoding="utf-8")

    info = load_version_info_from_text_file(str(path))

    # Windows хранит версию двумя 32-битными словами: (старшая<<16 | вторая) и
    # (третья<<16 | четвёртая).
    assert info.ffi.fileVersionMS == (0 << 16) | 1
    assert info.ffi.fileVersionLS == (51 << 16) | 0


def test_resource_carries_the_fields_people_see_in_file_properties(build_release) -> None:
    text = build_release.version_resource("0.1.51")

    for field in ("CompanyName", "FileDescription", "ProductName", "OriginalFilename"):
        assert field in text
    assert "0.1.51" in text
    assert "ZapretXmel.exe" in text
