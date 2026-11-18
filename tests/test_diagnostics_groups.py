"""Результаты диагностики группами: проблемы, к сведению, а успешные — свёрнуто."""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from app.core.config import Settings
from app.core.diagnostics.rules import Finding, Severity
from app.ui.controller import Controller
from app.ui.views.diagnostics import DiagnosticsView


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_passed_checks_are_folded_away(app) -> None:
    """Колонка зелёных галочек заслоняла собой одну настоящую проблему."""
    view = DiagnosticsView(Controller(Settings()))
    findings = [
        Finding(id="a", title="плохо", severity=Severity.ERROR),
        Finding(id="b", title="к сведению", severity=Severity.INFO),
        *(Finding(id=f"ok{i}", title=f"хорошо {i}", severity=Severity.OK) for i in range(5)),
    ]

    view._show_findings(findings)

    assert view._passed_box.isHidden()
    assert "5" in view._passed_toggle.text()
    view._passed_toggle.click()
    assert not view._passed_box.isHidden()
