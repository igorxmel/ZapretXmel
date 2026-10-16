"""Тесты удаления того, что программа принесла на компьютер.

Установщика у неё нет, и убрать её из «Программ и компонентов» нельзя:
если она не уберёт за собой сама, в системе останутся служба, драйвер и
сотня мегабайт ядра, о которых человек не знает.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import paths, uninstall


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Папка, где лежит всё: ядро, прокси, настройки."""
    for name in ("core/bin", "core/lists", "data/logs", "data/backups", "tgproxy"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "core" / "bin" / "winws.exe").write_text("", encoding="utf-8")
    (tmp_path / "data" / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "location.txt").write_text(str(tmp_path), encoding="utf-8")

    monkeypatch.setattr(paths, "app_root", lambda: tmp_path)
    paths.reset_cache()

    monkeypatch.setattr(uninstall.service, "is_installed", lambda: False)
    monkeypatch.setattr(uninstall.winws, "kill_all", lambda: 0)
    monkeypatch.setattr(uninstall.shortcut, "exists", lambda: False)

    yield tmp_path
    paths.reset_cache()


def test_core_is_removed_with_its_backups(installed: Path) -> None:
    result = uninstall.remove_core()

    assert not (installed / "core").exists()
    assert not (installed / "data" / "backups").exists()
    assert "папка ядра" in result.gone
    # Настройки при удалении одного ядра трогать нельзя.
    assert (installed / "data" / "config.json").exists()


def test_service_is_removed_before_the_files(
    installed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пока winws жив, файлы ядра заняты и папка не удалится."""
    order: list[str] = []
    monkeypatch.setattr(uninstall.service, "is_installed", lambda: True)
    monkeypatch.setattr(uninstall.service, "remove", lambda: order.append("служба"))
    monkeypatch.setattr(
        uninstall.winws, "kill_all", lambda: order.append("процессы") or 1
    )

    uninstall.remove_core()

    assert order == ["служба", "процессы"]


def test_proxy_is_removed_separately(installed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uninstall.telegram, "home", lambda: installed / "tgproxy")
    monkeypatch.setattr(
        uninstall.telegram.TelegramProxy, "is_running", lambda self: False
    )

    uninstall.remove_proxy()

    assert not (installed / "tgproxy").exists()
    assert (installed / "core").exists(), "ядро при удалении прокси не трогаем"


def test_everything_takes_settings_too(installed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uninstall.telegram, "home", lambda: installed / "tgproxy")
    monkeypatch.setattr(
        uninstall.telegram.TelegramProxy, "is_running", lambda self: False
    )

    uninstall.remove_everything()

    assert not (installed / "core").exists()
    assert not (installed / "tgproxy").exists()
    assert not (installed / "data").exists()
    assert not (installed / "location.txt").exists()


def test_busy_folder_is_reported_not_hidden(
    installed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если что-то удалить не вышло, об этом надо сказать, а не промолчать."""

    def refuse(_path):
        raise OSError("файл занят")

    monkeypatch.setattr(uninstall.shutil, "rmtree", refuse)

    result = uninstall.remove_core()

    assert "папка ядра" in result.kept
    assert "осталось" in result.summary


def test_leftovers_mention_the_executable(installed: Path) -> None:
    """Удалить работающий файл Windows не даст — надо предупредить заранее."""
    assert any("файл программы" in item for item in uninstall.leftovers())
