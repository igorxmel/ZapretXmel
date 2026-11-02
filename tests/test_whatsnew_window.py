"""Окно «что нового» со списком версий.

Нужен QApplication. Проверяется то, что ломалось при сборке: колесо над текстом
версии не прокручивало список, а видимый целиком текст оставался сдвигаемым.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.core import changelog
from app.ui.views.whatsnew import WhatsNewWindow

LONG = "\n\n".join(f"- пункт номер {index}" for index in range(40))
ENTRIES = [
    changelog.Entry("0.1.3", LONG),
    changelog.Entry("0.1.2", LONG),
    changelog.Entry("0.1.1", "x"),
]


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app: QApplication) -> WhatsNewWindow:
    shown = WhatsNewWindow(ENTRIES, "Заголовок")
    shown.show()
    QTest.qWait(50)
    yield shown
    shown.close()


def test_only_the_newest_version_is_open(window: WhatsNewWindow) -> None:
    assert [section.toggle.isChecked() for section in window.sections] == [True, False, False]


def test_closed_versions_are_not_parsed_in_advance(window: WhatsNewWindow) -> None:
    """Вся история — больше полусотни разделов, а открывают один-два."""
    assert window.sections[0]._notes is not None
    assert window.sections[1]._notes is None


def test_click_opens_and_closes_a_version(window: WhatsNewWindow) -> None:
    section = window.sections[1]

    QTest.mouseClick(section.toggle, Qt.MouseButton.LeftButton)
    assert section._notes is not None and not section._notes.isHidden()

    QTest.mouseClick(section.toggle, Qt.MouseButton.LeftButton)
    assert section._notes.isHidden()


def test_opened_notes_fit_without_own_scrolling(window: WhatsNewWindow) -> None:
    QTest.mouseClick(window.sections[1].toggle, Qt.MouseButton.LeftButton)
    QTest.qWait(50)

    notes = window.sections[1]._notes

    assert notes.height() >= notes.document().size().height()
    assert notes.verticalScrollBar().maximum() == 0


def test_wheel_over_notes_scrolls_the_list(window: WhatsNewWindow) -> None:
    bar = window.scroll.verticalScrollBar()
    target = window.sections[0]._notes.viewport()
    event = QWheelEvent(
        QPointF(10, 10),
        QPointF(target.mapToGlobal(QPoint(10, 10))),
        QPoint(0, 0),
        QPoint(0, -240),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )

    QApplication.sendEvent(target, event)

    assert bar.value() > 0


def test_single_version_has_no_dropdowns(app: QApplication) -> None:
    single = WhatsNewWindow(ENTRIES[:1], "Заголовок")

    assert not hasattr(single, "sections")
