"""Экран авто-подбора стратегии.

Главная причина, по которой это приложение вообще нужно: вместо того чтобы
руками запускать батники по очереди и смотреть, открылся ли ютуб, перебор
делается сам, с замером по каждому сервису и понятным итогом.

Проверяются все сервисы сразу, а не один выбранный: у разных провайдеров режут
разное, и пользователю нужно, чтобы работало всё. Итог показывается по каждому
сервису отдельно — если победитель что-то так и не починил, об этом сказано
прямо, а не спрятано в общей сумме.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import merge, strategies
from app.core.diagnostics import vpn
from app.core.probe import dpi, services
from app.core.probe.autopick import DPI_TARGET_LIMIT, Mode, Report, StrategyScore, save_report
from app.core.probe.http import supported_protocols
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, Chip, view_header
from app.ui.workers import AutoPickWorker, Task

COLUMNS = ("Стратегия", "Сервисы", "Пройдено", "Не прошло", "Блокировка", "Время")

DPI_CHIP = "Проверка DPI"

SERVICES_NOTE = (
    "<b>Что делает:</b> поднимает каждую стратегию и проверяет выбранные сервисы.<br>"
    "<b>Как считает:</b> сначала сравнивается число сервисов, заработавших целиком, "
    "и только потом общее число пройденных проверок — иначе стратегия, которая чинит "
    "ютуб и ломает дискорд, обошла бы ту, что чинит оба.<br>"
    "<b>Discord</b> проверяется не открытием страницы, а тремя шагами самого клиента: "
    "запрос к API, рукопожатие с гейтвеем и загрузка картинок."
)

DPI_NOTE = (
    "<b>Что делает:</b> шлёт на нейтральные хосты запрос с телом и просит прислать кусок "
    "данных в ответ, после чего считает, сколько байт реально прошло.<br>"
    "<b>Зачем:</b> показывает поведение самого канала, когда по сервисам всё чисто, "
    "а ощущение, что режут, остаётся."
)


class AutoPickView(QWidget):
    """Перебор стратегий с показом хода работы и применением лучшей."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._worker: AutoPickWorker | None = None
        self._suite_task: Task | None = None
        self._report: Report | None = None
        self._dpi_targets: list[dpi.DpiTarget] = []
        self._services: list[services.Service] = []
        self._service_chips: list[Chip] = []
        self._ignore_vpn = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Подбор стратегии",
                "Каждая стратегия поднимается по очереди и проверяется на одних и тех же "
                "сервисах. Первой строкой идёт замер без обхода — стратегия считается "
                "выигрышной, только если она его превзошла.",
            )
        )

        layout.addWidget(self._build_controls_card())
        layout.addWidget(self._build_results_card(), 1)

    def _build_controls_card(self) -> Card:
        card = Card()
        body = card.body()

        self._chips_row = QHBoxLayout()
        self._chips_row.setSpacing(SPACE["sm"])
        body.addLayout(self._chips_row)

        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])

        self._start_button = QPushButton("Запустить подбор")
        self._start_button.setObjectName("Primary")
        self._start_button.clicked.connect(self._start)
        row.addWidget(self._start_button)

        self._cancel_button = QPushButton("Остановить")
        self._cancel_button.setEnabled(False)
        self._cancel_button.clicked.connect(self._cancel)
        row.addWidget(self._cancel_button)

        self._apply_button = QPushButton("Применить лучшую")
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(self._apply_best)
        row.addWidget(self._apply_button)

        self._merge_button = QPushButton("Собрать из лучших частей")
        self._merge_button.setToolTip(
            "Соединяет рабочие секции нескольких стратегий в одну и тут же "
            "проверяет результат — вдруг получится лучше каждой из них"
        )
        self._merge_button.setVisible(False)
        self._merge_button.clicked.connect(self._merge_best)
        row.addWidget(self._merge_button)

        own_targets = QPushButton("Добавить свои цели")
        own_targets.setToolTip(
            "Открыть файл, где можно дописать свои сайты. Заголовок ### задаёт "
            "новый сервис — он появится здесь отдельной кнопкой."
        )
        own_targets.clicked.connect(self._open_user_targets)
        row.addWidget(own_targets)
        row.addStretch(1)
        body.addLayout(row)

        self._note = QLabel()
        self._note.setObjectName("Dim")
        self._note.setWordWrap(True)
        self._note.setTextFormat(Qt.TextFormat.RichText)
        body.addWidget(self._note)

        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.hide()
        body.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        body.addWidget(self._status)

        return card

    def _build_results_card(self) -> Card:
        card = Card("Результаты")
        body = card.body()

        self._verdict = QLabel("Подбор ещё не запускался")
        self._verdict.setObjectName("ViewSubtitle")
        self._verdict.setWordWrap(True)
        body.addWidget(self._verdict)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        for column in range(len(COLUMNS)):
            item = self._table.horizontalHeaderItem(column)
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter
                | (Qt.AlignmentFlag.AlignLeft if column < 2 else Qt.AlignmentFlag.AlignHCenter)
            )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, len(COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        body.addWidget(self._table, 1)

        return card

    # --- выбор того, что проверять ---------------------------------------

    def reload(self) -> None:
        """Перечитывает список сервисов: пользователь мог дописать свои цели."""
        self._ignore_vpn = False
        services.ensure_user_targets()
        self._rebuild_chips()
        self._mode_changed()
        self._warn_if_tunnel()

    def _rebuild_chips(self) -> None:
        while self._chips_row.count():
            item = self._chips_row.takeAt(0)
            if (widget := item.widget()) is not None:
                widget.deleteLater()

        self._services = services.discover()
        self._service_chips = []

        for service in self._services:
            chip = Chip(f"{service.name} · {service.size}", service.name)
            chip.setChecked(True)
            chip.clicked.connect(self._mode_changed)
            self._service_chips.append(chip)
            self._chips_row.addWidget(chip)

        self._dpi_chip = Chip(DPI_CHIP, "dpi")
        self._dpi_chip.clicked.connect(self._mode_changed)
        self._chips_row.addWidget(self._dpi_chip)
        self._chips_row.addStretch(1)

    def _current_mode(self) -> Mode:
        return "dpi" if self._dpi_chip.isChecked() else "services"

    def _selected_services(self) -> list[services.Service]:
        chosen = {chip.value for chip in self._service_chips if chip.isChecked()}
        return [service for service in self._services if service.name in chosen]

    def _mode_changed(self) -> None:
        dpi_mode = self._current_mode() == "dpi"
        for chip in self._service_chips:
            chip.setEnabled(not dpi_mode)

        if dpi_mode:
            self._note.setText(DPI_NOTE)
            count = len(self._dpi_targets) or "около 36"
            self._status.setText(f"Хостов в наборе: {count}, проверяется до {DPI_TARGET_LIMIT}.")
            return

        self._note.setText(SERVICES_NOTE)
        chosen = self._selected_services()
        checks = sum(service.size for service in chosen)
        self._status.setText(
            f"Выбрано сервисов: {len(chosen)}, проверок на стратегию: {checks}."
            if chosen
            else "Не выбрано ни одного сервиса."
        )

    def _warn_if_tunnel(self) -> None:
        # Быстрая проверка без PowerShell: полная занимает полсекунды и
        # подвешивала экран при каждом открытии.
        if (tunnel := vpn.detect_fast()) is not None:
            self._status.setStyleSheet(f"color: {COLORS['warning']};")
            self._status.setText(
                f"Сейчас трафик идёт через {tunnel.adapter}. Выключите VPN перед подбором — "
                "иначе проверка измерит туннель, а не вашего провайдера."
            )
            return

        self._status.setStyleSheet(f"color: {COLORS['text_muted']};")
        names = [name for name, _ in supported_protocols()]
        if "TLS1.3" not in names:
            self._status.setText(
                self._status.text()
                + " Системный curl здесь не умеет TLS 1.3 — на Windows 10 его нет в Schannel."
            )

    def _open_user_targets(self) -> None:
        services.ensure_user_targets()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(services.user_targets_file())))

    # --- прогон ---------------------------------------------------------

    def _start(self) -> None:
        specs = strategies.load_all()
        if not specs:
            self.controller.error.emit("Нет ни одной стратегии — сначала установите ядро.")
            return

        mode = self._current_mode()
        chosen = self._selected_services()
        if mode == "services" and not chosen:
            self.controller.error.emit("Отметьте хотя бы один сервис для проверки.")
            return

        if (tunnel := vpn.detect()) is not None and not self._ignore_vpn:
            self._warn_about_vpn(tunnel)
            return

        if mode == "dpi" and not self._dpi_targets:
            self._status.setText("Скачиваю список проверочных хостов…")
            self._start_button.setEnabled(False)
            self._suite_task = Task(dpi.load_suite)
            self._suite_task.done.connect(self._suite_loaded)
            self._suite_task.failed.connect(self._fail)
            self._suite_task.start()
            return

        self._launch(specs, mode, chosen)

    def _suite_loaded(self, targets: list[dpi.DpiTarget]) -> None:
        self._dpi_targets = targets
        self._start_button.setEnabled(True)
        self._launch(strategies.load_all(), "dpi", [])

    def _launch(self, specs: list, mode: Mode, chosen: list[services.Service]) -> None:
        self._table.setRowCount(0)
        self._report = None

        what = (
            f"{len(self._dpi_targets[:DPI_TARGET_LIMIT])} хостам"
            if mode == "dpi"
            else f"{len(chosen)} сервисам"
        )
        self._verdict.setStyleSheet(f"color: {COLORS['text_dim']};")
        self._verdict.setText(
            f"Проверяю {len(specs)} стратегий по {what}, плюс замер без обхода…"
        )

        # Шагов на один больше: первым идёт базовый замер.
        self._progress.setRange(0, len(specs) + 1)
        self._progress.setValue(0)
        self._progress.show()
        self._set_running(True)

        self._worker = AutoPickWorker(
            specs,
            mode=mode,
            chosen=chosen,
            dpi_targets=self._dpi_targets,
            timeout=self.controller.settings.probe_timeout,
            parallel=self.controller.settings.probe_parallel,
        )
        self._worker.progress.connect(self._status.setText)
        self._worker.strategy_done.connect(self._add_row)
        self._worker.done.connect(self._finish)
        self._worker.failed.connect(self._fail)
        self._worker.start()

    def _warn_about_vpn(self, tunnel: vpn.VpnInfo) -> None:
        """Останавливает прогон, пока трафик идёт через туннель."""
        answer = QMessageBox(self)
        answer.setWindowTitle("Включён VPN")
        answer.setIcon(QMessageBox.Icon.Warning)
        answer.setText(f"Трафик идёт через {tunnel.label}.")
        answer.setInformativeText(
            "Через туннель открывается всё подряд, поэтому подбор измерит VPN, "
            "а не вашего провайдера, и выберет случайную стратегию.\n\n"
            "Выключите VPN и запустите подбор заново."
        )
        run_anyway = answer.addButton("Всё равно запустить", QMessageBox.ButtonRole.DestructiveRole)
        answer.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        answer.exec()

        if answer.clickedButton() is run_anyway:
            self._ignore_vpn = True
            self._start()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._cancel_button.setEnabled(False)

    def _set_running(self, running: bool) -> None:
        self._start_button.setEnabled(not running)
        self._cancel_button.setEnabled(running)
        for chip in [*self._service_chips, self._dpi_chip]:
            chip.setEnabled(not running)
        if running:
            self._apply_button.setEnabled(False)

    def _add_row(self, score: StrategyScore) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._progress.setValue(row)

        if score.started:
            values = (
                score.name,
                score.services_label,
                str(score.ok),
                str(score.error),
                str(score.blocked) if score.blocked else "—",
                f"{score.median_ms:.0f} мс" if score.median_ms else "—",
            )
        else:
            values = (score.name, "не запустилась", "—", "—", "—", "—")

        for column, text in enumerate(values):
            item = QTableWidgetItem(text)
            if column >= 2:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if not score.started:
                item.setForeground(Qt.GlobalColor.gray)
            self._table.setItem(row, column, item)

        if score.is_baseline:
            self._mark_row(row, bold=True, color=COLORS["info"])

    def _mark_row(self, row: int, bold: bool = False, color: str | None = None) -> None:
        for column in range(len(COLUMNS)):
            item = self._table.item(row, column)
            if item is None:
                continue
            if bold:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            if color:
                item.setForeground(QColor(color))

    def _finish(self, report: Report) -> None:
        self._report = report
        self._set_running(False)
        self._progress.hide()
        self._rebuild_table(report)

        best = report.best
        suffix = " Прогон прерван." if report.cancelled else ""
        self._verdict.setText(report.verdict + suffix)
        self._apply_button.setEnabled(best is not None)

        # Жёлтым помечается и отсутствие победителя, и победитель с
        # недочинёнными сервисами: и то, и другое требует внимания.
        unfinished = best is None or bool(best.broken_services)
        self._verdict.setStyleSheet(
            f"color: {COLORS['warning'] if unfinished else COLORS['success']};"
        )

        self._offer_merge(report)

        path = save_report(report)
        self._status.setStyleSheet(f"color: {COLORS['text_muted']};")
        self._status.setText(f"Отчёт сохранён: {path.name}")

    def _rebuild_table(self, report: Report) -> None:
        """Пересобирает таблицу: базовый замер сверху, дальше по убыванию качества."""
        self._table.setRowCount(0)
        best = report.best

        if report.baseline is not None:
            self._add_row(report.baseline)

        for score in report.ranked:
            self._add_row(score)
            if best is not None and score.name == best.name:
                colour = COLORS["warning"] if score.broken_services else COLORS["success"]
                self._mark_row(self._table.rowCount() - 1, bold=True, color=colour)

    def _fail(self, message: str) -> None:
        self._set_running(False)
        self._start_button.setEnabled(True)
        self._progress.hide()
        self._verdict.setText("Подбор не удался")
        self._status.setStyleSheet(f"color: {COLORS['danger']};")
        self._status.setText(message)

    def _offer_merge(self, report: Report) -> None:
        """Предлагает собрать стратегию, если разные сервисы выиграли разные.

        Когда всё чинит одна стратегия, собирать нечего — кнопка не появляется.
        """
        self._plan = merge.plan_from_winners(report.service_winners)
        useful = report.mode == "services" and self._plan.is_useful
        self._merge_button.setVisible(useful)

        if useful:
            self._verdict.setText(
                report.verdict
                + f" Разные сервисы выиграли разные стратегии ({self._plan.describe()}) — "
                "можно попробовать собрать из них одну."
            )

    def _merge_best(self) -> None:
        """Собирает стратегию из частей и сразу отправляет её на перепроверку."""
        plan = getattr(self, "_plan", None)
        if plan is None or not plan.is_useful:
            return

        specs = [spec for name in plan.strategy_names if (spec := strategies.load_one(name))]
        if len(specs) < 2:
            self.controller.error.emit("Не удалось разобрать исходные стратегии.")
            return

        argv = merge.merge(specs)
        path = merge.save(argv, plan)
        built = strategies.load_one(path.stem)
        if built is None:
            self.controller.error.emit("Собранная стратегия не разобралась — проверьте её вручную.")
            return

        self._verdict.setStyleSheet(f"color: {COLORS['text_dim']};")
        self._verdict.setText(
            f"Собрана стратегия «{built.name}» из {len(specs)} частей, "
            f"секций {len(built.sections)}. Проверяю, лучше ли она исходных…"
        )
        self._merge_button.setVisible(False)
        self._launch([built], "services", self._selected_services())

    def _apply_best(self) -> None:
        if self._report is None or self._report.best is None:
            return
        name = self._report.best.name
        self.controller.select_strategy(name)
        self.controller.stop()
        self.controller.start()
        self._status.setText(f"Применена стратегия «{name}»")
