"""Автообновление: что ставится само, что нет, и что спрашивается перед включением.

Нужен QApplication. Поводом стало желание не жать «Обновить» на каждой новой
версии ядра и прокси, но так, чтобы молчаливая установка не стала сюрпризом.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from app.core import updates
from app.core.config import Settings
from app.core.updater import github, selfupdate
from app.ui import dialogs
from app.ui.controller import Controller
from app.ui.views.updates import UpdatesView

HASH = github.Asset(name=selfupdate.ASSET_NAME + ".sha256", url="", size=64)


def _available(what: str, prerelease: bool = False, assets=None) -> updates.Available:
    release = github.Release(
        tag="v9",
        name="9",
        body="",
        published_at="2026-11-01T00:00:00Z",
        prerelease=prerelease,
        assets=list(assets or []),
    )
    return updates.Available(what, "1", "9", "updates", release)


APP = _available(updates.APP, assets=[HASH])
CORE = _available(updates.CORE)
PROXY = _available(updates.PROXY)


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> UpdatesView:
    monkeypatch.setattr(Settings, "save", lambda _self: None)
    return UpdatesView(Controller(Settings()))


def test_program_goes_last() -> None:
    """После программы может понадобиться перезапуск — остальное к нему уже стоит."""
    assert updates.auto_candidates([APP, CORE, PROXY], [], set()) == [PROXY, CORE, APP]


def test_ignored_source_is_not_installed() -> None:
    assert updates.auto_candidates([CORE, PROXY], [updates.SOURCE_CORE], set()) == [PROXY]


def test_testing_builds_are_never_installed() -> None:
    testing = _available(updates.APP, prerelease=True, assets=[HASH])

    assert updates.auto_candidates([testing], [], set()) == []


def test_program_without_hash_is_not_installed() -> None:
    """Без хеша недокачанный .exe встал бы на место рабочего, и некому было бы заметить."""
    bare = _available(updates.APP, assets=[github.Asset(selfupdate.ASSET_NAME, "", 1)])

    assert updates.auto_candidates([bare], [], set()) == []


def test_github_digest_is_enough_to_verify() -> None:
    exe = github.Asset(selfupdate.ASSET_NAME, "", 1, digest="ab" * 32)
    signed = _available(updates.APP, assets=[exe])

    assert updates.auto_candidates([signed], [], set()) == [signed]


def test_failed_version_is_not_retried() -> None:
    assert updates.auto_candidates([CORE], [], {(updates.CORE, "9")}) == []


def test_all_ignored_means_no_background_check() -> None:
    assert updates.everything_ignored(list(updates.ALL_SOURCES))
    assert not updates.everything_ignored([updates.SOURCE_CORE])


def test_old_switch_off_becomes_all_ignored() -> None:
    """Прежняя галочка «Сообщать о новых версиях» выключала проверку целиком."""
    settings = Settings.from_dict({"notify_updates": False, "ignored_updates": ["core"]})

    assert settings.ignored_updates == ["app", "core", "proxy"]
    assert Settings.from_dict({"notify_updates": True}).ignored_updates == []


def test_auto_update_is_off_by_default() -> None:
    assert Settings().auto_update is False
    assert Settings.from_dict({"auto_update": True}).auto_update is True


def test_declined_warning_keeps_auto_update_off(
    view: UpdatesView, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dialogs, "confirm", lambda *args, **kwargs: False)

    view._auto_box.setChecked(True)
    view._toggle_auto(True)

    assert not view._auto_box.isChecked()
    assert view.controller.settings.auto_update is False


def test_accepted_warning_turns_auto_update_on(
    view: UpdatesView, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = []
    monkeypatch.setattr(dialogs, "confirm", lambda *args, **kwargs: asked.append(kwargs) or True)
    changed = []
    view.update_policy_changed.connect(lambda: changed.append(True))

    view._toggle_auto(True)

    assert view.controller.settings.auto_update is True
    assert asked[0]["action"] == "Включить автообновление"
    assert changed


def test_turning_off_needs_no_warning(view: UpdatesView, monkeypatch: pytest.MonkeyPatch) -> None:
    view.controller.settings.auto_update = True
    monkeypatch.setattr(dialogs, "confirm", lambda *args, **kwargs: pytest.fail("спросили"))

    view._toggle_auto(False)

    assert view.controller.settings.auto_update is False


def test_testing_builds_moved_to_updates(
    view: UpdatesView, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dialogs, "confirm", lambda *args, **kwargs: False)

    view._testing.setChecked(True)
    view._toggle_testing(True)

    assert not view._testing.isChecked()
    assert view.controller.settings.testing_builds is False


def test_auto_install_reports_back(view: UpdatesView, monkeypatch: pytest.MonkeyPatch) -> None:
    """Прокси ставится тем же путём, что по кнопке, а о конце узнаёт окно."""
    monkeypatch.setattr(view, "_update_proxy", lambda: None)
    monkeypatch.setattr("app.core.telegram.is_running_anywhere", lambda: False)
    done = []
    view.auto_installed.connect(lambda what, version: done.append((what, version)))

    assert view.auto_install(PROXY)
    view._proxy_updated("9")

    assert done == [(updates.PROXY, "9")]
    assert view._auto == ""


def test_manual_install_is_not_reported_as_auto(
    view: UpdatesView, monkeypatch: pytest.MonkeyPatch
) -> None:
    done = []
    view.auto_installed.connect(lambda what, version: done.append(what))

    view._proxy_updated("9")

    assert done == []


def test_auto_failure_is_reported(view: UpdatesView, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(view, "_update_proxy", lambda: None)
    monkeypatch.setattr("app.core.telegram.is_running_anywhere", lambda: False)
    failed = []
    view.auto_failed.connect(lambda what, message: failed.append((what, message)))

    view.auto_install(PROXY)
    view._proxy_failed("нет сети")

    assert failed == [(updates.PROXY, "нет сети")]


# --- окно: когда ставить и когда перезапускаться ---------------------------------


@pytest.fixture
def window(app: QApplication, monkeypatch: pytest.MonkeyPatch):
    from app import __version__
    from app.ui.shell import MainWindow

    monkeypatch.setattr(Settings, "save", lambda _self: None)
    shown = MainWindow(
        Settings(first_run_done=True, last_seen_version=__version__, auto_update=True)
    )
    shown.controller._timer.stop()
    shown._updates_timer.stop()
    # Настоящая установка ядра выключает обход на этой машине — в тестах её нет.
    monkeypatch.setattr(shown.views["updates"], "auto_install", lambda item: True)
    yield shown
    shown._quitting = True
    shown.close()


def test_nothing_starts_while_busy(window, monkeypatch: pytest.MonkeyPatch) -> None:
    """Обновление ядра выключает обход — посреди подбора это обрывает работу."""
    started = []
    monkeypatch.setattr(window.views["updates"], "auto_install", started.append)
    window._found_updates = [CORE]
    window._busy_sections["autopick"] = "Подбор стратегии"

    window._auto_update()

    assert started == []


def test_idle_program_installs_first_candidate(window, monkeypatch: pytest.MonkeyPatch) -> None:
    started = []
    monkeypatch.setattr(
        window.views["updates"], "auto_install", lambda item: started.append(item) or True
    )
    window._found_updates = [APP, CORE, PROXY]

    window._auto_update()

    assert started == [PROXY]


def test_switched_off_does_nothing(window, monkeypatch: pytest.MonkeyPatch) -> None:
    started = []
    monkeypatch.setattr(window.views["updates"], "auto_install", started.append)
    window.settings.auto_update = False
    window._found_updates = [CORE]

    window._auto_update()

    assert started == []


def test_visible_window_is_not_restarted(window, monkeypatch: pytest.MonkeyPatch) -> None:
    """Закрыть окно у человека из-под рук хуже, чем подождать следующего запуска."""
    window.show()
    restarted = []
    monkeypatch.setattr(selfupdate, "restart", restarted.append)
    messages = []
    monkeypatch.setattr(window, "_notify", messages.append)

    window._auto_installed(updates.APP, "9")

    assert restarted == []
    assert "после перезапуска" in messages[0]
    assert (updates.APP, "9") in window._auto_done


def test_staged_program_is_not_offered_again(window, monkeypatch: pytest.MonkeyPatch) -> None:
    """Новая сборка уже на месте, ждёт запуска — звать на неё снова незачем."""
    window.show()
    monkeypatch.setattr(window, "_notify", lambda text: None)
    window._found_updates = [APP]
    window._auto_installed(updates.APP, "9")

    window._updates_found([APP, CORE])

    assert [item.what for item in window._found_updates] == [updates.CORE]


def test_hidden_window_restarts_into_tray(window, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import singleton

    window.hide()
    restarted = []
    monkeypatch.setattr(selfupdate, "restart", restarted.append)
    monkeypatch.setattr(window, "quit", lambda: None)

    window._auto_installed(updates.APP, "9")

    assert restarted and singleton.TRAY_FLAG in restarted[0]


def test_failure_is_not_retried(window, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(window, "_notify", lambda text: None)
    window._found_updates = [CORE]

    window._auto_failed(updates.CORE, "нет сети")

    assert updates.auto_candidates(window._found_updates, [], window._auto_done) == []
