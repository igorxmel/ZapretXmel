"""Тесты проверки окружения, которая выполняется до запуска программы.

Собранная одним файлом программа прописывает свою временную папку в `PATH`,
`QT_PLUGIN_PATH` и `QML2_IMPORT_PATH`. При запуске одной такой программы из
другой эти пути достаются по наследству, и Qt берёт библиотеки из чужой
папки, которая исчезает вместе с родителем: ровно так ломалось
самообновление.

Сам хук при импорте ничего не делает — вне собранной версии `sys._MEIPASS`
нет, и проверять нечего.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from runtime_hook_clean_env import _clean, _foreign, _inherited_from_another_build  # noqa: E402

MINE = r"C:\Users\user\AppData\Local\Temp\_MEI000011111"
FOREIGN = r"C:\Users\user\AppData\Local\Temp\_MEI000099999"


def test_own_folder_is_not_foreign() -> None:
    assert not _foreign(MINE + r"\PyQt6\Qt6\bin", MINE)


def test_another_build_folder_is_foreign() -> None:
    assert _foreign(FOREIGN + r"\PyQt6\Qt6\bin", MINE)


def test_ordinary_paths_are_not_foreign() -> None:
    assert not _foreign(r"C:\Windows\system32;C:\Program Files\Git\bin", MINE)


def test_foreign_folder_in_path_is_detected(monkeypatch) -> None:
    """Главный признак: из PATH берутся библиотеки Qt."""
    monkeypatch.setenv("PATH", rf"{FOREIGN}\PyQt6\Qt6in;C:\Windows\system32")

    assert _inherited_from_another_build(MINE)


def test_clean_environment_keeps_everything_else(monkeypatch) -> None:
    monkeypatch.setenv("PATH", rf"{FOREIGN}in;C:\Windows\system32")
    monkeypatch.setenv("QT_PLUGIN_PATH", rf"{FOREIGN}\PyQt6\Qt6\plugins")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\user")

    environment = _clean(MINE)

    assert environment["PATH"] == r"C:\Windows\system32"
    assert "QT_PLUGIN_PATH" not in environment
    assert environment["USERPROFILE"] == r"C:\Users\user"


def test_own_paths_survive_cleaning(monkeypatch) -> None:
    """Свои пути трогать нельзя — без них программа сама не запустится."""
    monkeypatch.setenv("PATH", rf"{MINE}\PyQt6\Qt6in;C:\Windows\system32")

    assert _clean(MINE)["PATH"] == rf"{MINE}\PyQt6\Qt6in;C:\Windows\system32"


def test_clean_environment_drops_the_unpacking_marker(monkeypatch) -> None:
    monkeypatch.setenv("_MEIPASS2", FOREIGN)

    assert "_MEIPASS2" not in _clean(MINE)
