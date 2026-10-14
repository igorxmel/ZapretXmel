"""Экран диагностики.

Повторяет проверки консольного меню апстрима, но каждая находка здесь —
не строка в логе, а пункт с объяснением, зачем это нужно, и, где возможно,
с кнопкой починки.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.diagnostics import collectors, rules
from app.core.diagnostics.rules import Finding, Severity
from app.core.probe import discord
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SEVERITY_COLORS, SPACE
from app.ui.views.ai_panel import AiPanel
from app.ui.widgets import Card, Divider, view_header
from app.ui.workers import Task

SEVERITY_MARKS: dict[Severity, str] = {
    Severity.ERROR: "✕",
    Severity.WARNING: "!",
    Severity.INFO: "i",
    Severity.OK: "✓",
}


class FindingRow(QWidget):
    """Одна находка: метка важности, заголовок, пояснение и действие."""

    def __init__(self, finding: Finding, on_fix, parent: QWidget | None = None):
        super().__init__(parent)
        color = SEVERITY_COLORS[finding.severity]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, SPACE["sm"], 0, SPACE["sm"])
        layout.setSpacing(SPACE["md"])

        mark = QLabel(SEVERITY_MARKS[finding.severity])
        mark.setFixedWidth(18)
        mark.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        mark.setStyleSheet(f"color: {color}; font-weight: 600;")
        layout.addWidget(mark)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)

        title = QLabel(finding.title)
        title.setWordWrap(True)
        if finding.severity is not Severity.OK:
            title.setStyleSheet("font-weight: 600;")
        text_column.addWidget(title)

        if finding.detail:
            detail = QLabel(finding.detail)
            detail.setObjectName("Dim")
            detail.setWordWrap(True)
            text_column.addWidget(detail)

        if finding.link:
            link = QPushButton("Подробности")
            link.setObjectName("Ghost")
            link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(finding.link)))
            row = QHBoxLayout()
            row.addWidget(link)
            row.addStretch(1)
            text_column.addLayout(row)

        layout.addLayout(text_column, 1)

        if finding.fix:
            button = QPushButton(finding.fix_label or "Исправить")
            button.clicked.connect(lambda: on_fix(finding))
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignTop)


class DiagnosticsView(QWidget):
    """Проверка системы на известные причины неработающего обхода."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._task: Task | None = None
        self._ran = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Диагностика",
                "Проверяет то, что чаще всего мешает обходу: конфликтующие программы, "
                "выключенные системные службы, неудачное расположение папки.",
            )
        )

        controls = QHBoxLayout()
        controls.setSpacing(SPACE["md"])

        self._run_button = QPushButton("Проверить систему")
        self._run_button.setObjectName("Primary")
        self._run_button.clicked.connect(self.run_checks)
        controls.addWidget(self._run_button)

        # Второстепенная кнопка: нужна не всем, поэтому не спорит за внимание
        # с основной проверкой.
        self._discord_button = QPushButton("отдельно проверить Discord")
        self._discord_button.setObjectName("Ghost")
        self._discord_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._discord_button.setToolTip(
            "Проверяет вход, гейтвей и загрузку картинок по отдельности — "
            "обычная проверка показывает успех, даже когда клиент не подключается"
        )
        self._discord_button.clicked.connect(self.run_discord_checks)
        controls.addWidget(self._discord_button)

        self._summary = QLabel("Проверка ещё не запускалась")
        self._summary.setObjectName("Dim")
        controls.addWidget(self._summary, 1)
        layout.addLayout(controls)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = Card("Результаты проверки")
        self._container.body().setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)

        columns = QHBoxLayout()
        columns.setSpacing(SPACE["lg"])
        columns.addWidget(self._scroll, 3)

        self.ai_panel = AiPanel(controller)
        columns.addWidget(self.ai_panel, 2)
        layout.addLayout(columns, 1)

        self._placeholder = QLabel(
            "Проверка занимает пару секунд: приложение опрашивает службы Windows, "
            "смотрит системные настройки и состояние сборки zapret."
        )
        self._placeholder.setObjectName("Dim")
        self._placeholder.setWordWrap(True)
        self._container.body().addWidget(self._placeholder)
        self._container.body().addStretch(1)

    def reload(self) -> None:
        """Первое открытие экрана сразу запускает проверку — её для этого и открывают."""
        self.ai_panel.reload()
        if not self._ran:
            self.run_checks()

    def run_checks(self) -> None:
        self._ran = True
        self._run_button.setEnabled(False)
        self._summary.setText("Собираю сведения о системе…")

        self._task = Task(self._collect)
        self._task.done.connect(self._show_findings)
        self._task.failed.connect(self._fail)
        self._task.start()

    @staticmethod
    def _collect() -> list[Finding]:
        return rules.evaluate(collectors.collect())

    def _show_findings(self, findings: list[Finding]) -> None:
        self._run_button.setEnabled(True)
        self._clear()

        body = self._container.body()
        for finding in findings:
            body.addWidget(FindingRow(finding, self._apply_fix))
            body.addWidget(Divider())
        body.addStretch(1)

        problems = rules.problems(findings)
        if not problems:
            self._summary.setText(f"Проблем не найдено, проверок пройдено: {len(findings)}")
            self._summary.setStyleSheet(f"color: {COLORS['success']};")
            return

        errors = sum(1 for finding in problems if finding.severity is Severity.ERROR)
        serious = f", из них серьёзных: {errors}" if errors else ""
        self._summary.setText(f"Найдено проблем: {len(problems)}{serious}")
        self._summary.setStyleSheet(
            f"color: {COLORS['danger'] if errors else COLORS['warning']};"
        )

    def run_discord_checks(self) -> None:
        self._discord_button.setEnabled(False)
        self._summary.setStyleSheet(f"color: {COLORS['text_dim']};")
        self._summary.setText("Проверяю Discord по шагам…")

        self._task = Task(discord.check_all)
        self._task.done.connect(self._show_discord)
        self._task.failed.connect(self._fail)
        self._task.start()

    def _show_discord(self, results: list[discord.StepResult]) -> None:
        """Показывает результат по шагам: что именно у Discord не отвечает."""
        self._discord_button.setEnabled(True)
        self._clear()

        body = self._container.body()
        for result in results:
            finding = Finding(
                id=f"discord_{result.step}",
                severity=Severity.OK if result.ok else Severity.ERROR,
                title=f"{result.title} — {'отвечает' if result.ok else 'не отвечает'}",
                detail=(
                    f"{result.detail} · {result.elapsed_ms:.0f} мс"
                    if result.ok
                    else f"{result.meaning} Ответ: {result.detail}"
                ),
            )
            body.addWidget(FindingRow(finding, self._apply_fix))
            body.addWidget(Divider())

        note = QLabel(discord.summarise(results))
        note.setObjectName("Dim")
        note.setWordWrap(True)
        body.addWidget(note)
        body.addStretch(1)

        broken = [result for result in results if not result.ok]
        self._summary.setStyleSheet(
            f"color: {COLORS['danger'] if broken else COLORS['success']};"
        )
        self._summary.setText(
            f"Discord: не отвечает шагов — {len(broken)}"
            if broken
            else "Discord отвечает полностью"
        )

    def _apply_fix(self, finding: Finding) -> None:
        if rules.apply_fix(finding.fix):
            self.controller.message.emit(f"Исправлено: {finding.title}")
            self.run_checks()
        else:
            self.controller.error.emit(f"Не удалось исправить: {finding.title}")

    def _fail(self, message: str) -> None:
        self._run_button.setEnabled(True)
        self._discord_button.setEnabled(True)
        self._summary.setText(f"Проверка не удалась: {message}")
        self._summary.setStyleSheet(f"color: {COLORS['danger']};")

    def _clear(self) -> None:
        body = self._container.body()
        # Первый элемент — заголовок карточки, его оставляем.
        while body.count() > 1:
            item = body.takeAt(1)
            if (widget := item.widget()) is not None:
                widget.deleteLater()
