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
    monkeypatch.setattr(uninstall.telegram, "kill_running", lambda: 0)
    monkeypatch.setattr(uninstall.service, "unload_windivert", lambda: True)
    monkeypatch.setattr(uninstall.winws, "kill_all", lambda: 0)
    monkeypatch.setattr(uninstall.shortcut, "remove_all", list)

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
    monkeypatch.setattr(uninstall.telegram, "kill_running", lambda: 0)

    uninstall.remove_proxy()

    assert not (installed / "tgproxy").exists()
    assert (installed / "core").exists(), "ядро при удалении прокси не трогаем"


def test_running_proxy_is_stopped_before_its_folder_goes(
    installed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Включённый прокси держит свой .exe, и папка не удаляется.

    Снимать его надо по пути к файлу: запущенный экземпляр принадлежит
    контроллеру, а здесь его нет. Прежний код создавал новый `TelegramProxy`,
    тот про чужой процесс ничего не знал, отвечал «не запущен» — и включённый
    прокси оставался на диске, хотя ядро на ходу удалялось.
    """
    order: list[str] = []
    monkeypatch.setattr(uninstall.telegram, "home", lambda: installed / "tgproxy")
    monkeypatch.setattr(
        uninstall.telegram, "kill_running", lambda: order.append("снят") or 1
    )
    monkeypatch.setattr(
        uninstall.shutil, "rmtree", lambda path, onexc=None: order.append("файлы")
    )

    result = uninstall.remove_proxy()

    assert order == ["снят", "файлы"]
    assert "запущенный прокси" in result.gone


def test_everything_takes_settings_too(installed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uninstall.telegram, "home", lambda: installed / "tgproxy")
    monkeypatch.setattr(uninstall.telegram, "kill_running", lambda: 0)

    uninstall.remove_everything()

    assert not (installed / "core").exists()
    assert not (installed / "tgproxy").exists()
    assert not (installed / "data").exists()
    assert not (installed / "location.txt").exists()


def test_busy_folder_is_reported_not_hidden(
    installed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если что-то удалить не вышло, об этом надо сказать, а не промолчать."""

    def refuse(path, onexc=None):
        """Повторяет поведение Windows: файл занят, папка остаётся на месте."""
        onexc(None, str(Path(path) / "bin" / "WinDivert64.sys"), OSError("файл занят"))

    monkeypatch.setattr(uninstall.shutil, "rmtree", refuse)

    result = uninstall.remove_core()

    assert "папка ядра" in result.kept
    assert "осталось" in result.summary


def test_locked_file_does_not_save_the_rest(
    installed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Один занятый файл не оставляет на диске всё остальное.

    `rmtree` обходит папку сверху вниз и без `onexc` бросает исключение на
    первом же запертом файле. На ядре это оборачивалось худшим из исходов:
    драйвер `WinDivert.dll` стирался, `winws.exe` оставался, ядро выглядело
    установленным, а служба падала с «не ответила своевременно».
    """
    core = installed / "core"
    locked = core / "bin" / "WinDivert64.sys"
    locked.parent.mkdir(parents=True, exist_ok=True)
    locked.write_text("драйвер", encoding="utf-8")
    (core / "bin" / "winws.exe").write_text("winws", encoding="utf-8")

    real_rmtree = uninstall.shutil.rmtree

    def keep_the_driver(path, onexc=None):
        """Windows отдаёт WinError 5 на загруженном драйвере, остальное пускает."""
        for item in sorted(Path(path).rglob("*"), key=lambda p: (-len(p.parts), p.name)):
            if item == locked or not item.exists():
                continue
            if item.is_dir():
                if not any(item.iterdir()):
                    item.rmdir()
            else:
                item.unlink()
        onexc(None, str(locked), OSError("файл занят"))

    monkeypatch.setattr(uninstall.shutil, "rmtree", keep_the_driver)
    result = uninstall.remove_core()
    monkeypatch.setattr(uninstall.shutil, "rmtree", real_rmtree)

    assert locked.exists(), "занятый файл остаётся — его и нельзя удалить"
    assert not (core / "bin" / "winws.exe").exists(), "всё остальное должно исчезнуть"
    assert "папка ядра" in result.kept


def test_leftovers_mention_the_executable(installed: Path) -> None:
    """Удалить работающий файл Windows не даст — надо предупредить заранее."""
    assert any("файл программы" in item for item in uninstall.leftovers())


def test_driver_is_unloaded_before_the_files(
    installed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пока драйвер в ядре, WinDivert64.sys заперт и папка ядра не уходит."""
    order: list[str] = []

    monkeypatch.setattr(
        uninstall.service, "unload_windivert", lambda: order.append("драйвер") or True
    )
    monkeypatch.setattr(
        uninstall.shutil, "rmtree", lambda path, onexc=None: order.append("файлы")
    )

    uninstall.remove_core()

    assert order[0] == "драйвер"


def test_stuck_driver_asks_for_a_reboot(
    installed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Невыгруженный драйвер — не «ошибка», а объяснимая причина остатка."""
    monkeypatch.setattr(uninstall.service, "unload_windivert", lambda: False)

    result = uninstall.remove_core()

    assert result.needs_reboot
    assert "перезагрузки" in result.summary


def test_log_is_released_before_the_folder_goes(
    installed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Открытый журнал лежит внутри удаляемой папки и держит её.

    Та же беда, на которой спотыкался переезд: `data/logs/app.log` открыт,
    Windows удалить его не даёт, и папка настроек остаётся целиком.
    """
    released: list[bool] = []
    monkeypatch.setattr(
        uninstall.logging_setup, "release_file", lambda: released.append(True)
    )
    monkeypatch.setattr(uninstall.service, "unload_windivert", lambda: True)

    uninstall.remove_everything()

    assert released, "журнал надо отпустить, иначе папка настроек не удалится"
    assert not (installed / "data").exists()
