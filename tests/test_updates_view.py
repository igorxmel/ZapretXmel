"""Подсветка того, что устарело, и галочки «не напоминать».

Нужен QApplication. Поводом стали люди, которые обновляли ядро и считали, что
обновили всё: прокси на соседней кнопке оставался старым, и этого не было видно.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from app.core import updates
from app.core.config import Settings
from app.core.updater import github
from app.ui.controller import Controller
from app.ui.views.updates import CORE, PROXY, UpdatesView


def _available(what: str, section: str = "updates") -> updates.Available:
    release = github.Release(tag="v9", name="9", body="", published_at="2026-11-01T00:00:00Z")
    return updates.Available(what, "1", "9", section, release)


CORE_UPDATE = _available(updates.CORE)
PROXY_UPDATE = _available(updates.PROXY, "telegram")


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> UpdatesView:
    monkeypatch.setattr(Settings, "save", lambda _self: None)
    return UpdatesView(Controller(Settings()))


def _alert(view: UpdatesView, source: str) -> bool:
    return view._source_buttons[source].property("alert") is True


def test_outdated_source_is_highlighted(view: UpdatesView) -> None:
    view.set_pending([PROXY_UPDATE])

    assert _alert(view, PROXY)
    assert not _alert(view, CORE)


def test_highlight_goes_after_update(view: UpdatesView) -> None:
    view.set_pending([PROXY_UPDATE])
    view.set_pending([])

    assert not _alert(view, PROXY)


def test_ignored_source_is_not_highlighted(view: UpdatesView) -> None:
    view.set_pending([PROXY_UPDATE])

    view._set_ignored(PROXY, True)

    assert not _alert(view, PROXY)
    assert view.controller.settings.ignored_updates == [PROXY]

    view._set_ignored(PROXY, False)

    assert _alert(view, PROXY)
    assert view.controller.settings.ignored_updates == []


def test_view_opens_the_source_that_needs_updating(view: UpdatesView) -> None:
    """Иначе человек видел актуальное ядро и уходил, не заметив прокси."""
    assert view._source == CORE

    view.show_known_updates([PROXY_UPDATE])

    assert view._source == PROXY
    assert view._source_buttons[PROXY].isChecked()


def test_ignored_source_does_not_steal_the_card(view: UpdatesView) -> None:
    view._set_ignored(PROXY, True)

    view.show_known_updates([PROXY_UPDATE])

    assert view._source == CORE


def test_checkbox_follows_selected_source(view: UpdatesView) -> None:
    view._set_ignored(PROXY, True)

    view._switch_source(PROXY)
    assert view._source_ignore.isChecked()

    view._switch_source(CORE)
    assert not view._source_ignore.isChecked()


def test_core_version_does_not_stay_on_the_proxy_page(view: UpdatesView) -> None:
    view.set_pending([CORE_UPDATE])
    view._switch_source(CORE)
    assert view._row_latest._value.text() != "—"

    view._switch_source(PROXY)

    assert view._row_latest._value.text() == "—"


def test_selected_chip_has_room_for_bold_text(view: UpdatesView) -> None:
    """Выбранная кнопка пишется жирным, и текст в ней обрезался по краям."""
    for button in view._source_buttons.values():
        assert button.minimumWidth() >= button.sizeHint().width()


def test_reminders_skip_ignored_sources() -> None:
    found = [CORE_UPDATE, PROXY_UPDATE]

    assert updates.without_ignored(found, [PROXY]) == [CORE_UPDATE]
    assert updates.without_ignored(found, []) == found


def test_ignored_choice_survives_restart() -> None:
    assert Settings.from_dict({"ignored_updates": [PROXY]}).ignored_updates == [PROXY]
    assert Settings.from_dict({}).ignored_updates == []
