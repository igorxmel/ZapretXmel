"""Тесты обнаружения чужой установки zapret.

Служба у сборки Flowseal называется так же, как наша, — это одна и та же
служба. Поэтому у человека, который уже пользовался zapret вручную, интерфейс
показывал чужую установку как свою. Здесь проверяется, что мы отличаем её от
собственной папки и находим корень сборки по пути к winws.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import foreign, paths


@pytest.fixture
def own_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Своя установка в отдельной папке — чтобы не зависеть от настоящей."""
    root = tmp_path / "ZapretXmel"
    (root / "core" / "bin").mkdir(parents=True)
    monkeypatch.setattr(paths, "app_root", lambda: root)
    paths.reset_cache()
    yield root
    paths.reset_cache()


# --- разбор командной строки службы -------------------------------------


def test_quoted_path_with_spaces_is_parsed() -> None:
    binpath = '"C:\\Program Files\\zapret\\bin\\winws.exe" --wf-tcp=80,443 --dpi-desync=fake'

    assert foreign.executable_from_binpath(binpath) == Path(
        "C:\\Program Files\\zapret\\bin\\winws.exe"
    )


def test_bare_path_is_parsed() -> None:
    binpath = "D:\\zapret\\bin\\winws.exe --wf-udp=443"

    assert foreign.executable_from_binpath(binpath) == Path("D:\\zapret\\bin\\winws.exe")


def test_path_without_arguments_is_parsed() -> None:
    assert foreign.executable_from_binpath("D:\\zapret\\bin\\winws.exe") == Path(
        "D:\\zapret\\bin\\winws.exe"
    )


def test_garbage_gives_nothing() -> None:
    assert foreign.executable_from_binpath("") is None
    assert foreign.executable_from_binpath("служба без пути") is None


# --- корень сборки ------------------------------------------------------


def test_root_is_one_level_above_bin() -> None:
    assert foreign.bundle_root(Path("D:\\zapret\\bin\\winws.exe")) == Path("D:\\zapret")


def test_unexpected_layout_falls_back_to_the_file_folder() -> None:
    """Раскладка может быть любой — приблизительный путь полезнее пустого."""
    assert foreign.bundle_root(Path("D:\\tools\\winws.exe")) == Path("D:\\tools")


# --- обнаружение --------------------------------------------------------


def test_nothing_found_when_system_is_clean(
    own_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(foreign.service, "is_installed", lambda: False)
    monkeypatch.setattr(foreign.psutil, "process_iter", lambda _attrs: [])

    assert foreign.detect() is None


def test_service_pointing_elsewhere_is_foreign(
    own_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(foreign.service, "is_installed", lambda: True)
    monkeypatch.setattr(
        foreign.service,
        "installed_binpath",
        lambda: '"D:\\zapret\\bin\\winws.exe" --wf-tcp=80,443',
    )
    monkeypatch.setattr(foreign.psutil, "process_iter", lambda _attrs: [])

    found = foreign.detect()

    assert found is not None
    assert found.root == Path("D:\\zapret")
    assert found.by_service
    assert not found.by_process


def test_our_own_service_is_not_foreign(own_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Главная проверка: собственная установка не должна пугать человека."""
    monkeypatch.setattr(foreign.service, "is_installed", lambda: True)
    monkeypatch.setattr(
        foreign.service, "installed_binpath", lambda: f'"{paths.winws_exe()}" --wf-tcp=80,443'
    )
    monkeypatch.setattr(foreign.psutil, "process_iter", lambda _attrs: [])

    assert foreign.detect() is None


class FakeProcess:
    def __init__(self, name: str, exe: str):
        self.info = {"name": name, "exe": exe}


def test_running_process_from_another_folder_is_foreign(
    own_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(foreign.service, "is_installed", lambda: False)
    monkeypatch.setattr(
        foreign.psutil,
        "process_iter",
        lambda _attrs: [FakeProcess("winws.exe", "D:\\zapret\\bin\\winws.exe")],
    )

    found = foreign.detect()

    assert found is not None
    assert found.by_process
    assert found.root == Path("D:\\zapret")


def test_our_own_process_is_not_foreign(own_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(foreign.service, "is_installed", lambda: False)
    monkeypatch.setattr(
        foreign.psutil,
        "process_iter",
        lambda _attrs: [FakeProcess("winws.exe", str(paths.winws_exe()))],
    )

    assert foreign.detect() is None


def test_service_wins_over_process(own_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Служба важнее: именно её переписывает включение обхода."""
    monkeypatch.setattr(foreign.service, "is_installed", lambda: True)
    monkeypatch.setattr(
        foreign.service, "installed_binpath", lambda: '"D:\\zapret\\bin\\winws.exe"'
    )
    monkeypatch.setattr(
        foreign.psutil,
        "process_iter",
        lambda _attrs: [FakeProcess("winws.exe", "E:\\other\\bin\\winws.exe")],
    )

    found = foreign.detect()

    assert found is not None
    assert found.root == Path("D:\\zapret")
    assert found.by_service


def test_other_processes_are_ignored(own_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(foreign.service, "is_installed", lambda: False)
    monkeypatch.setattr(
        foreign.psutil,
        "process_iter",
        lambda _attrs: [FakeProcess("chrome.exe", "C:\\Chrome\\chrome.exe")],
    )

    assert foreign.detect() is None
