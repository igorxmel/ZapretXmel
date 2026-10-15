"""Тесты окружения для дочерних процессов.

Собранная одним файлом программа распаковывает себя во временную папку и
оставляет её путь в `_MEIPASS2`. Дочерний процесс, увидев эту переменную,
решает, что распаковывать нечего, и работает с чужой папкой — а она исчезает
вместе с родителем. Именно так ломалось самообновление: новая версия падала
с «no Qt platform plugin could be initialized».
"""

from __future__ import annotations

import os

import pytest

from app.core.process import child_environment


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch):
    """Изображает запуск из собранной версии."""
    temporary = r"C:\Users\user\AppData\Local\Temp\_MEI000020882"
    monkeypatch.setattr("app.core.process.sys.frozen", True, raising=False)
    monkeypatch.setattr("app.core.process.sys._MEIPASS", temporary, raising=False)
    return temporary


def test_meipass2_is_dropped(frozen: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Главная причина поломки: по этой переменной дочерний процесс берёт чужую папку."""
    monkeypatch.setenv("_MEIPASS2", frozen)

    assert "_MEIPASS2" not in child_environment()


def test_temporary_folder_leaves_the_search_paths(
    frozen: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", os.pathsep.join([frozen, r"C:\Windows\system32"]))
    monkeypatch.setenv("QT_PLUGIN_PATH", frozen + r"\PyQt6\Qt6\plugins")

    environment = child_environment()

    assert environment["PATH"] == r"C:\Windows\system32"
    assert "QT_PLUGIN_PATH" not in environment


def test_original_values_are_restored(frozen: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Сборка сохраняет подменённые значения рядом, с суффиксом _ORIG."""
    monkeypatch.setenv("SOME_PATH", frozen + r"\lib")
    monkeypatch.setenv("SOME_PATH_ORIG", r"C:\Program Files\lib")

    environment = child_environment()

    assert environment["SOME_PATH"] == r"C:\Program Files\lib"
    assert "SOME_PATH_ORIG" not in environment


def test_untouched_variables_survive(frozen: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USERPROFILE", r"C:\Users\user")

    assert child_environment()["USERPROFILE"] == r"C:\Users\user"


def test_sources_run_returns_environment_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """Из исходников временной папки нет, и чистить нечего."""
    monkeypatch.delattr("app.core.process.sys._MEIPASS", raising=False)
    monkeypatch.setenv("PATH", r"C:\Windows\system32")

    assert child_environment()["PATH"] == r"C:\Windows\system32"
