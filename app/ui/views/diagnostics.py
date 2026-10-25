"""Экран диагностики.

Повторяет проверки консольного меню апстрима, но каждая находка здесь —
не строка в логе, а пункт с объяснением, зачем это нужно, и, где возможно,
с кнопкой починки.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core import nettools
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
        self._checked_at: datetime | None = None

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

        columns = QHBoxLayout()
        columns.setSpacing(SPACE["lg"])
        columns.addWidget(self._scroll, 3)
        columns.addWidget(self._build_network_card(), 2)
        layout.addLayout(columns, 1)

        self._placeholder = QLabel(
            "Проверка занимает пару секунд: приложение опрашивает службы Windows, "
            "смотрит системные настройки и состояние сборки zapret."
        )
        self._placeholder.setObjectName("Dim")
        self._placeholder.setWordWrap(True)
        self._container.body().addWidget(self._placeholder)
        self._container.body().addStretch(1)

    def _with_time(self, text: str) -> str:
        """Дописывает к итогу время проверки.

        Экран открывают повторно, и без времени непонятно, относится ли
        «проблем не найдено» к нынешнему состоянию или к тому, что было
        полчаса назад, до правки настроек.
        """
        self._checked_at = datetime.now()
        return f"{text} · проверено в {self._checked_at:%H:%M}"

    def _build_network_card(self) -> Card:
        """Проверки и действия, относящиеся к блокировкам.

        Не «всё, что умеет Windows»: `netsh` и `ipconfig` умеют десятки
        вещей, из которых к обходу относятся четыре. Список из двадцати
        кнопок помешал бы найти нужную.
        """
        card = Card("Сеть")
        body = card.body()

        hint = QLabel(
            "Каждое действие отвечает на свой вопрос. Запускается по одному "
            "— результат появится здесь же."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        body.addWidget(hint)

        # Свой адрес для трёх проверок, которым он нужен. Без него они берут
        # типичные сайты, и на вопрос «а у меня Instagram откроется?» ответить
        # было нечем: адрес вводить было некуда.
        self._site = QLineEdit()
        self._site.setPlaceholderText("Свой сайт, например instagram.com (необязательно)")
        self._site.setToolTip(
            "Подмена DNS, «Где рвётся» и трассировка проверят этот адрес. "
            "Пусто — возьмут типичные сайты."
        )
        self._site.textChanged.connect(self._refresh_tips)
        self._site.returnPressed.connect(self._run_default)
        body.addWidget(self._site)

        # (название, пояснение, как это выглядит в консоли, что запустить, нужен ли адрес)
        # Подсказка строится из тех же списков аргументов, которые запускаются:
        # написанная отдельной строкой, она рано или поздно описывала бы не то,
        # что кнопка делает.
        self._net_actions = (
            (
                "Сбросить кэш DNS",
                "Старые ответы остаются после правки hosts и смены DNS, и "
                "сайт продолжает не открываться, хотя всё уже настроено",
                lambda site: nettools.shown(nettools.flush_command()),
                lambda host: nettools.flush_dns(),
                False,
            ),
            (
                "Проверить подмену DNS",
                "Провайдеры отдают для заблокированных доменов свой адрес — "
                "тогда обход бессилен, соединение уходит не туда. Программа "
                "сверяет ответ системы с ответом по DNS-over-HTTPS, которого "
                "консоль не умеет, поэтому ближайшее в консоли — лишь половина "
                "проверки",
                lambda site: f"nslookup {site}  и  nslookup {site} 1.1.1.1",
                lambda host: nettools.check_dns(host or nettools.PROBE_DOMAIN),
                True,
            ),
            (
                "Где рвётся соединение",
                "Проверяет по уровням — DNS, адрес, имя сайта, ответ "
                "сервера — и говорит, поможет ли здесь обход вообще. Идёт по "
                "порядку и останавливается на первом отказе",
                lambda site: f"Test-NetConnection {site} -Port 443  и  curl.exe -v https://{site}",
                lambda host: nettools.where_blocked(host),
                True,
            ),
            (
                "Трассировка",
                "Где именно рвётся путь: у вас, у провайдера или дальше",
                lambda site: nettools.shown(nettools.trace_command(site)),
                lambda host: nettools.trace(host),
                True,
            ),
            (
                "Проверить размер пакета",
                "Слишком большие пакеты режутся молча: страницы "
                "открываются, а файлы качаются рывками",
                lambda site: nettools.shown(nettools.mtu_command()),
                lambda host: nettools.check_mtu(),
                False,
            ),
        )

        self._net_buttons = []
        for title, _tip, _command, worker, _needs_site in self._net_actions:
            button = QPushButton(title)
            button.clicked.connect(lambda _, run=worker: self._run_net(run))
            body.addWidget(button)
            self._net_buttons.append(button)
        self._refresh_tips()

        self._net_result = QPlainTextEdit()
        self._net_result.setReadOnly(True)
        self._net_result.setPlaceholderText("Здесь появится результат")
        body.addWidget(self._net_result, 1)

        return card

    def _site_host(self) -> str:
        """Нормализованный адрес из поля. Пусто — поле пустое или это не адрес."""
        return nettools.normalize_host(self._site.text())

    def _refresh_tips(self) -> None:
        """Подсказка кнопки: пояснение и то, как это выглядит в консоли.

        Адрес в команде подставляется живьём, из поля, — человек видит именно ту
        строку, которую набрал бы руками.
        """
        site = self._site_host() or "<сайт>"
        for button, (_title, tip, command, _worker, _needs) in zip(
            self._net_buttons, self._net_actions, strict=True
        ):
            button.setToolTip(f"{tip}\n\nВ консоли: {command(site)}")

    def _run_default(self) -> None:
        """Enter в поле — «Где рвётся»: из трёх проверок с адресом она главная."""
        self._net_buttons[2].click()

    def _run_net(self, worker) -> None:
        """Запускает проверку в потоке: ping и tracert идут десятки секунд."""
        raw = self._site.text().strip()
        host = self._site_host()
        if raw and not host:
            self._net_result.setPlainText(
                f"«{raw}» не похоже на адрес сайта. Нужно имя вроде instagram.com — "
                "без пробелов и без лишних знаков."
            )
            return

        for button in self._net_buttons:
            button.setEnabled(False)
        self._net_result.setPlainText("Проверяю…")

        self._net_task = Task(lambda: worker(host))
        self._net_task.done.connect(self._show_net)
        self._net_task.failed.connect(self._net_failed)
        self._net_task.start()

    def _show_net(self, outcome) -> None:
        for button in self._net_buttons:
            button.setEnabled(True)

        parts = [f"{outcome.title}: {outcome.verdict}"]
        if outcome.detail:
            parts.append(outcome.detail)
        if outcome.lines:
            parts.append("\n".join(outcome.lines))
        self._net_result.setPlainText("\n\n".join(parts))

    def _net_failed(self, message: str) -> None:
        for button in self._net_buttons:
            button.setEnabled(True)
        self._net_result.setPlainText(message)

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
            self._summary.setText(
                self._with_time(f"Проблем не найдено, проверок пройдено: {len(findings)}")
            )
            self._summary.setStyleSheet(f"color: {COLORS['success']};")
            return

        errors = sum(1 for finding in problems if finding.severity is Severity.ERROR)
        serious = f", из них серьёзных: {errors}" if errors else ""
        self._summary.setText(self._with_time(f"Найдено проблем: {len(problems)}{serious}"))
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
