"""Выбор стратегии и быстрая проверка: общие для обзора и мини-окна.

Нужен QApplication. Поводом стал человек, который выбирал стратегию в списке, не включал
её и нажимал проверку, а результат принимал за оценку этой стратегии.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from app.core.config import Settings
from app.ui.controller import Controller, Status
from app.ui.theme.tokens import COLORS
from app.ui.views import controls
from app.ui.views.controls import (
    CHECK_AS_IS,
    CHECK_ENABLE,
    QuickPanel,
    measured_note,
    pending_strategy,
    strategy_hint,
)

OFF = Status(core_present=True)
ON = Status(core_present=True, winws_count=1, active_strategy="general")


class FakeCheck:
    results: list = []
    everything_works = True
    working = ["YouTube"]
    broken: list[str] = []
    verdict = "всё работает"


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> QuickPanel:
    monkeypatch.setattr(Settings, "save", lambda _self: None)
    monkeypatch.setattr("app.core.stability.record", lambda *_, **__: None)
    controller = Controller(Settings(selected_strategy="general"))
    controller.status = ON
    monkeypatch.setattr(controller, "start", lambda: None)
    monkeypatch.setattr(controller, "restart", lambda: None)
    monkeypatch.setattr(controller, "refresh", lambda: controller.status)
    shown = QuickPanel(controller)
    shown._strategy_box.addItem("general", "general")
    shown._strategy_box.addItem("ALT3", "ALT3")
    shown.ran = []
    monkeypatch.setattr(shown, "_run_quick_check", lambda: shown.ran.append(True))
    return shown


def _choose(panel: QuickPanel, name: str) -> None:
    panel._strategy_box.setCurrentIndex(panel._strategy_box.findData(name))


# --- выбрана, но не работает ------------------------------------------------


@pytest.mark.parametrize(
    ("status", "chosen", "pending"),
    [
        (OFF, "ALT3", "ALT3"),
        (ON, "ALT3", "ALT3"),
        (ON, "general", ""),
        (OFF, "", ""),
        (Status(core_present=False), "ALT3", ""),
        # Обход поднят снаружи, и его стратегию мы не знаем: сверять не с чем.
        (Status(core_present=True, winws_count=1), "ALT3", ""),
    ],
)
def test_pending_strategy(status: Status, chosen: str, pending: str) -> None:
    assert pending_strategy(status, chosen) == pending


def test_hint_names_what_really_works() -> None:
    assert "general" in strategy_hint(ON, "ALT3")
    assert "не включена" in strategy_hint(OFF, "ALT3")
    assert strategy_hint(ON, "general") == ""


def test_hint_and_primary_button_appear_only_when_not_applied(panel: QuickPanel) -> None:
    _choose(panel, "general")
    panel._show_hint()
    assert panel._hint.isHidden()
    assert panel._apply_button.objectName() != "Primary"

    _choose(panel, "ALT3")
    assert not panel._hint.isHidden()
    assert panel._apply_button.objectName() == "Primary"

    _choose(panel, "general")
    assert panel._hint.isHidden()
    assert panel._apply_button.objectName() != "Primary"


def test_choice_is_not_rolled_back_by_polling(panel: QuickPanel) -> None:
    """Выбор откатывался сам при первом опросе после потери фокуса."""
    _choose(panel, "ALT3")

    panel.apply_status(ON)
    panel.apply_status(ON)

    assert panel._chosen() == "ALT3"


def test_change_on_another_screen_is_picked_up(panel: QuickPanel) -> None:
    panel.controller.settings.selected_strategy = "ALT3"

    panel.apply_status(ON)

    assert panel._chosen() == "ALT3"


# --- что проверено ----------------------------------------------------------


def test_note_when_bypass_is_off() -> None:
    assert "выключен" in measured_note(OFF, "ALT3")


def test_note_says_the_chosen_one_was_not_tested() -> None:
    note = measured_note(ON, "ALT3")

    assert "general" in note and "ALT3" in note and "а не" in note


def test_note_names_the_tested_strategy() -> None:
    note = measured_note(ON, "general")

    assert "general" in note and "а не" not in note


def test_note_warns_about_vpn() -> None:
    status = Status(core_present=True, winws_count=1, active_strategy="general", active_vpn="Meta")

    assert "Meta" in measured_note(status, "general")


def test_result_includes_what_was_tested(panel: QuickPanel) -> None:
    _choose(panel, "general")

    panel._quick_done(FakeCheck())

    text = panel._check_result.text()
    assert "Всё работает" in text and "general" in text
    assert COLORS["success"] in panel._check_result.styleSheet()


# --- вопрос перед проверкой -------------------------------------------------


def _answer(panel: QuickPanel, monkeypatch: pytest.MonkeyPatch, answer: str) -> list[str]:
    asked: list[str] = []

    def ask(pending: str) -> str:
        asked.append(pending)
        return answer

    monkeypatch.setattr(panel, "_ask_about_pending", ask)
    monkeypatch.setattr(controls.QTimer, "singleShot", lambda _ms, call: call())
    return asked


def test_applied_strategy_is_checked_without_questions(
    panel: QuickPanel, monkeypatch: pytest.MonkeyPatch
) -> None:
    _choose(panel, "general")
    asked = _answer(panel, monkeypatch, CHECK_ENABLE)

    panel._check_clicked()

    assert asked == []
    assert panel.ran == [True]


def test_enable_and_check_applies_first(panel: QuickPanel, monkeypatch: pytest.MonkeyPatch) -> None:
    _choose(panel, "ALT3")
    asked = _answer(panel, monkeypatch, CHECK_ENABLE)
    applied: list[str] = []
    monkeypatch.setattr(
        panel.controller, "select_strategy", lambda name: applied.append(name)
    )

    panel._check_clicked()

    assert asked == ["ALT3"]
    assert applied == ["ALT3"]
    assert panel.ran == [True]


def test_check_as_is_changes_nothing(panel: QuickPanel, monkeypatch: pytest.MonkeyPatch) -> None:
    _choose(panel, "ALT3")
    _answer(panel, monkeypatch, CHECK_AS_IS)
    monkeypatch.setattr(
        panel.controller, "select_strategy", lambda _name: pytest.fail("включать не просили")
    )

    panel._check_clicked()

    assert panel.ran == [True]


def test_closed_question_does_nothing(panel: QuickPanel, monkeypatch: pytest.MonkeyPatch) -> None:
    _choose(panel, "ALT3")
    _answer(panel, monkeypatch, "")

    panel._check_clicked()

    assert panel.ran == []
