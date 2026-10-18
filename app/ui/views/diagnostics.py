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
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SEVERITY_COLORS, SPACE
from app.ui.views.aiwindow import AiWindow
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
        self._ai_window: AiWindow | None = None

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

        # Отдельной проверки Discord здесь больше нет: те же три шага
        # давно идут в быстрой проверке и в подборе, а вторая кнопка рядом
        # с «Проверить систему» означала для человека непонятный выбор.
        self._ai_button = QPushButton("ИИ диагностика")
        self._ai_button.setToolTip(
            "Отдельное окно: разбор неполадки нейросетью и выгрузка пакета "
            "для любого чат-бота"
        )
        self._ai_button.clicked.connect(self._open_ai)
        controls.addWidget(self._ai_button)

        self._summary = QLabel("Проверка ещё не запускалась")
        self._summary.setObjectName("Dim")
        controls.addWidget(self._summary, 1)
        layout.addLayout(controls)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = Card("Результаты проверки")
        self._container.body().setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)

        # Результатам отдан весь экран: разбор нейросетью переехал в своё
        # окно, и делить ширину больше не с чем.
        layout.addWidget(self._scroll, 1)

        self._placeholder = QLabel(
            "Проверка занимает пару секунд: приложение опрашивает службы Windows, "
            "смотрит системные настройки и состояние сборки zapret."
        )
        self._placeholder.setObjectName("Dim")
        self._placeholder.setWordWrap(True)
        self._container.body().addWidget(self._placeholder)
        self._container.body().addStretch(1)

    def _open_ai(self) -> None:
        """Открывает окно разбора. Одно на всё приложение, а не по окну на нажатие."""
        if self._ai_window is None:
            self._ai_window = AiWindow(self)
        self._ai_window.show()
        self._ai_window.raise_()
        self._ai_window.activateWindow()

    def reload(self) -> None:
        """Первое открытие экрана сразу запускает проверку — её для этого и открывают."""
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
