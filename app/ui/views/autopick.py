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

import time

from PyQt6.QtCore import QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import coverage, merge, repair, strategies
from app.core.batfile import StrategySpec
from app.core.diagnostics import vpn
from app.core.probe import dpi, services
from app.core.probe.autopick import DPI_TARGET_LIMIT, Mode, Report, StrategyScore, save_report
from app.core.probe.http import supported_protocols
from app.ui import dialogs
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, Chip, IconButton, ShineProgressBar, view_header
from app.ui.workers import AutoPickWorker, Task


# Блокировки меняются без предупреждения, а результат выглядит окончательным.
def clock(seconds: float) -> str:
    """«0:42», «1:05» — время подбора."""
    seconds = max(0, round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def timing(elapsed: float, done: int, total: int, stops_early: bool) -> str:
    """«Прошло 0:12 · осталось около 0:40».

    Оценка — по средней уже проверенных стратегий: после ускорения подбора они идут
    почти ровно, по паре секунд. С остановкой на первой рабочей это потолок, а не
    обещание: подбор может закончиться раньше.
    """
    text = f"Прошло {clock(elapsed)}"
    left = total - done
    if done <= 0 or left <= 0:
        return text
    rest = clock(elapsed / done * left)
    return text + (f" · осталось не больше {rest}" if stops_early else f" · осталось около {rest}")


RESULT_LIFETIME_NOTE = (
    "Подбор действует неопределённое время: лучшая стратегия может отвалиться "
    "уже через час использования. Перестало работать — запустите подбор снова."
)

START_TEXT = "Запустить подбор"

COLUMNS = ("Стратегия", "Сервисы", "Пройдено", "Не прошло", "Блокировка", "Время")
SERVICES_COLUMN = COLUMNS.index("Сервисы")

DPI_CHIP = "Проверка DPI"

# Пояснения — за кнопкой «?»: на экране они стояли абзацами над кнопками, и за ними
# терялось главное — что выбрано и что нажимать.
HELP_TEXT = (
    "Каждая стратегия по очереди поднимается и проверяется на выбранных сервисах. "
    "Первой строкой идёт замер без обхода: стратегия считается выигрышной, только если "
    "она его превзошла.\n\n"
    "Сначала сравнивается число сервисов, заработавших целиком, и только потом общее число "
    "пройденных проверок — иначе стратегия, которая чинит YouTube и ломает Discord, обошла "
    "бы ту, что чинит оба. Discord проверяется тремя шагами самого клиента: запрос к API, "
    "рукопожатие с гейтвеем и загрузка картинок.\n\n"
    "«Проверка DPI» шлёт на нейтральные хосты запрос с телом и считает, сколько байт "
    "реально прошло: показывает поведение канала, когда по сервисам всё чисто, а ощущение, "
    "что режут, остаётся.\n\n"
    "«+» открывает файл своих целей: заголовок ### в нём задаёт новый сервис, и он "
    "появится здесь отдельной кнопкой.\n\n" + RESULT_LIFETIME_NOTE
)


class _WholeLabel(QLabel):
    """Надпись с переносом, которая не даёт разметке себя поджать.

    Разметка оценивает переносимый текст не по настоящей ширине, и когда места мало —
    во время подбора появляются полоса прогресса и длинный вердикт, — поджимала
    надписи, а не таблицу, которой и положено сжиматься: последняя строка уходила
    под край. Здесь минимум — ровно столько строк, сколько текст займёт при этой ширине.
    """

    def _whole(self, hint: QSize) -> QSize:
        # Своя оценка Qt для переносимого текста берёт не ту ширину и ошибается вдвое
        # в обе стороны, поэтому высота — ровно по тексту при нынешней ширине.
        need = self.heightForWidth(self.width()) if self.width() > 0 else -1
        return QSize(hint.width(), need if need > 0 else hint.height())

    def sizeHint(self) -> QSize:  # noqa: N802 — имя задано Qt
        return self._whole(super().sizeHint())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 — имя задано Qt
        return self._whole(super().minimumSizeHint())

    def resizeEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        super().resizeEvent(event)
        # Разметка запоминает минимум; при новой ширине его надо пересчитать. Высота
        # от этого не меняет ширину, так что пересчёт не зацикливается.
        if event.oldSize().width() != event.size().width():
            self.updateGeometry()


class AutoPickView(QWidget):
    """Перебор стратегий с показом хода работы и применением лучшей."""

    # Долгая работа: боковое меню рисует кружок, а трей сообщает о
    # завершении, если окно успели свернуть.
    busy_changed = pyqtSignal(bool)

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._worker: AutoPickWorker | None = None
        self._suite_task: Task | None = None
        self._report: Report | None = None
        self._dpi_targets: list[dpi.DpiTarget] = []
        # Сборка, которая сейчас на проверке.
        self._built: StrategySpec | None = None
        self._uncovered: list[str] = []
        self._services: list[services.Service] = []
        self._service_chips: list[Chip] = []
        self._ignore_vpn = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Как на обзоре: когда окно низкое, а идёт подбор — полоса прогресса, вердикт в
        # две строки, предупреждение о VPN, — места на всё не хватало, и Qt обрезал
        # текст в карточках. С прокруткой страница остаётся целой, а в обычном окне
        # выглядит как раньше: таблица по-прежнему растягивается на свободное место.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Подбор стратегии",
                "Перебирает стратегии и находит ту, при которой работают выбранные сервисы.",
                aside=self._help_button(),
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

        # Одна кнопка: «Запустить подбор», а пока он идёт — «Остановить» на том же месте.
        # Две рядом, из которых одна всегда серая, только занимали место.
        self._start_button = QPushButton(START_TEXT)
        self._start_button.setObjectName("Primary")
        self._start_button.clicked.connect(self._run_clicked)
        row.addWidget(self._start_button)

        self._apply_button = QPushButton("Применить лучшую")
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(self._apply_best)
        row.addWidget(self._apply_button)

        self._merge_button = QPushButton("Собрать из лучших частей")
        self._merge_button.setToolTip(
            "Берёт за основу одну стратегию и подставляет в секции нужных сервисов "
            "способ обхода от других. Результат появится в списке стратегий, только "
            "если на проверке окажется лучше исходных"
        )
        self._merge_button.setVisible(False)
        self._merge_button.clicked.connect(self._merge_best)
        row.addWidget(self._merge_button)

        row.addStretch(1)
        body.addLayout(row)

        # Полный прогон — по умолчанию: только он даёт таблицу по всем стратегиям. Но
        # если нужна просто рабочая, быстрее начать с тех, что работали раньше, и
        # остановиться на первой подошедшей.
        self._stop_early = QCheckBox("Остановиться на первой, где работает всё, и включить её")
        self._stop_early.setToolTip(
            "Сначала проверяются избранные и те, что у вас работали дольше всего. "
            "Как только найдётся стратегия, при которой работают все отмеченные "
            "сервисы, подбор остановится и сразу её включит — обычно за несколько "
            "секунд. Таблицы по всем стратегиям тогда не будет"
        )
        self._stop_early.setChecked(self.controller.settings.autopick_stop_early)
        self._stop_early.toggled.connect(self._toggle_stop_early)
        body.addWidget(self._stop_early)

        body.addWidget(self._build_coverage_box())

        self._progress = ShineProgressBar()
        self._progress.setTextVisible(False)
        self._progress.hide()
        body.addWidget(self._progress)

        # Сколько прошло и сколько примерно осталось. Тикает раз в секунду, а оценка
        # уточняется с каждой проверенной стратегией.
        self._timing = QLabel("")
        self._timing.setObjectName("Muted")
        self._timing.hide()
        body.addWidget(self._timing)
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._show_timing)
        self._started_at = 0.0
        self._done = 0
        self._planned = 0
        self._early_run = False

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        body.addWidget(self._status)

        return card

    def _build_coverage_box(self) -> QWidget:
        """Свои сайты вне списков: подбор их проверит, но ни одна стратегия на них не повлияет."""
        self._coverage_box = QWidget()
        row = QHBoxLayout(self._coverage_box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE["sm"])

        self._coverage_note = QLabel("")
        self._coverage_note.setObjectName("Muted")
        self._coverage_note.setWordWrap(True)
        self._coverage_note.setStyleSheet(f"color: {COLORS['warning']};")
        row.addWidget(self._coverage_note, 1)

        self._coverage_button = QPushButton("Добавить в мой список")
        self._coverage_button.setToolTip(
            "Допишет эти сайты в «Свои домены» в разделе «Списки». Убрать их можно там же."
        )
        self._coverage_button.clicked.connect(self._add_to_own_list)
        row.addWidget(self._coverage_button)

        self._coverage_box.hide()
        return self._coverage_box

    def _show_coverage(self) -> None:
        self._uncovered = coverage.own_uncovered_hosts()
        self._coverage_box.setVisible(bool(self._uncovered))
        if self._uncovered:
            self._coverage_note.setText(
                f"Нет в списках: {', '.join(self._uncovered)}. Подбор проверит эти сайты, "
                "но ни одна стратегия на них не повлияет."
            )

    def _add_to_own_list(self) -> None:
        coverage.add_to_own_list(self._uncovered)
        self._show_coverage()
        self.controller.message.emit(
            "Сайты добавлены в свой список. Если обход включён, перезапустите его."
        )

    def _build_results_card(self) -> Card:
        card = Card("Результаты")
        body = card.body()

        self._verdict = _WholeLabel("Подбор ещё не запускался")
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
        self._show_coverage()
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

        # Свои цели — рядом с сервисами, к которым они и добавятся, а не кнопкой внизу.
        self._add_targets = QPushButton("+")
        self._add_targets.setObjectName("Chip")
        self._add_targets.setToolTip(
            "Добавить свои цели: откроется файл, где можно дописать сайты. "
            "Заголовок ### задаёт новый сервис — он появится здесь отдельной кнопкой"
        )
        self._add_targets.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_targets.clicked.connect(self._open_user_targets)
        self._chips_row.addWidget(self._add_targets)

        self._dpi_chip = Chip(DPI_CHIP, "dpi")
        self._dpi_chip.clicked.connect(self._mode_changed)
        self._chips_row.addWidget(self._dpi_chip)
        self._chips_row.addStretch(1)

    def _toggle_stop_early(self, enabled: bool) -> None:
        self.controller.settings.autopick_stop_early = enabled
        self.controller.settings.save()

    def _stops_early(self, mode: Mode) -> bool:
        """В проверке DPI сервисов нет — и «работает всё» проверять не по чему."""
        return mode == "services" and self._stop_early.isChecked()

    def _current_mode(self) -> Mode:
        return "dpi" if self._dpi_chip.isChecked() else "services"

    def _selected_services(self) -> list[services.Service]:
        chosen = {chip.value for chip in self._service_chips if chip.isChecked()}
        return [service for service in self._services if service.name in chosen]

    def _mode_changed(self) -> None:
        dpi_mode = self._current_mode() == "dpi"
        for chip in self._service_chips:
            chip.setEnabled(not dpi_mode)
        self._stop_early.setEnabled(not dpi_mode)

        # В режиме DPI сервисы не проверяются, и столбец про них стоял бы
        # пустым у всех строк подряд — прочерк напротив каждой стратегии
        # читается как «ничего не нашлось», а не «здесь это не меряется».
        self._table.setColumnHidden(SERVICES_COLUMN, dpi_mode)

        if dpi_mode:
            count = len(self._dpi_targets) or "около 36"
            self._status.setText(f"Хостов в наборе: {count}, проверяется до {DPI_TARGET_LIMIT}.")
            return

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

    def _help_button(self) -> IconButton:
        # «i», а не «?»: вопрос в кружке уже стоит в заголовке окна и открывает
        # справку по всей программе — одинаковые значки путали.
        button = IconButton("info", "Как устроен подбор", size=24, icon_size=18)
        button.clicked.connect(self._show_help)
        return button

    def _show_help(self) -> None:
        dialogs.tell(self, "Подбор стратегии", "Как устроен подбор", HELP_TEXT)

    def _run_clicked(self) -> None:
        if self.controller.picking:
            self._cancel()
        else:
            self._start()

    def _start(self) -> None:
        """Отклик — сразу, подготовка — следующим кадром.

        Раньше кнопка 2–3 секунды не отвечала: до запуска окно читало все стратегии и
        проверяло VPN через PowerShell, и всё это в своём потоке.
        """
        self._start_button.setEnabled(False)
        self._start_button.setText("Готовлю подбор…")
        QTimer.singleShot(0, self._start_now)

    def _ready(self) -> None:
        """Кнопка снова «Запустить подбор» — подбор так и не начался."""
        self._start_button.setText(START_TEXT)
        self._start_button.setEnabled(True)

    def _start_now(self) -> None:
        if self.controller.repair.running:
            self.controller.error.emit("Идёт починка, дождитесь её конца.")
            self._ready()
            return

        specs = strategies.load_all()
        if not specs:
            self.controller.error.emit("Нет ни одной стратегии — сначала установите ядро.")
            self._ready()
            return

        mode = self._current_mode()
        chosen = self._selected_services()
        if mode == "services" and not chosen:
            self.controller.error.emit("Отметьте хотя бы один сервис для проверки.")
            self._ready()
            return

        # Быстрая проверка, по адресу выхода. Полная спрашивала PowerShell и держала
        # кнопку секунд шесть, а при VPN в режиме TUN всё равно приходила к тому же.
        if (tunnel := vpn.detect_fast()) is not None and not self._ignore_vpn:
            self._ready()
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

        if self._stops_early(mode):
            names = repair.ordered(
                [spec.name for spec in specs], list(self.controller.settings.favorites)
            )
            by_name = {spec.name: spec for spec in specs}
            specs = [by_name[name] for name in names]
        self._launch(specs, mode, chosen, stop_early=self._stops_early(mode))

    def _suite_loaded(self, targets: list[dpi.DpiTarget]) -> None:
        self._dpi_targets = targets
        self._start_button.setEnabled(True)
        self._launch(strategies.load_all(), "dpi", [])

    def _launch(
        self,
        specs: list,
        mode: Mode,
        chosen: list[services.Service],
        stop_early: bool = False,
    ) -> None:
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
            + (" Начинаю с тех, что работали раньше, и остановлюсь на первой рабочей."
               if stop_early else "")
        )
        ignored = coverage.uncovered_target_names()

        # Шагов на один больше: первым идёт базовый замер.
        self._progress.setRange(0, len(specs) + 1)
        self._progress.setValue(0)
        self._progress.show()
        self._set_running(True)

        self._started_at = time.monotonic()
        self._done = 0
        self._planned = len(specs)
        self._early_run = stop_early
        self._show_timing()
        self._timing.show()
        self._clock.start()

        self._worker = AutoPickWorker(
            specs,
            mode=mode,
            chosen=chosen,
            dpi_targets=self._dpi_targets,
            timeout=self.controller.settings.probe_timeout,
            parallel=self.controller.settings.probe_parallel,
            stop_when=(lambda score: repair.fully_works(score, ignored)) if stop_early else None,
        )
        self._worker.progress.connect(self._status.setText)
        self._worker.strategy_done.connect(self._strategy_done)
        self._worker.done.connect(self._finish)
        self._worker.failed.connect(self._fail)
        self._worker.start()

    def _warn_about_vpn(self, tunnel: vpn.VpnInfo) -> None:
        """Останавливает прогон, пока трафик идёт через туннель."""
        run_anyway = dialogs.confirm(
            self,
            "Включён VPN",
            f"Трафик идёт через {tunnel.label}.",
            "Через туннель открывается всё подряд, поэтому подбор измерит VPN, "
            "а не вашего провайдера, и выберет случайную стратегию.\n\n"
            "Выключите VPN и запустите подбор заново.",
            action="Всё равно запустить",
            danger=True,
        )

        if run_anyway:
            self._ignore_vpn = True
            self._start_now()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._start_button.setEnabled(False)
            self._start_button.setText("Останавливаю…")

    def _set_running(self, running: bool) -> None:
        # Подбор идёт минутами, и уйти на другую вкладку — нормально.
        # Пусть боковое меню показывает, что здесь ещё работают.
        self.busy_changed.emit(running)
        self.controller.picking = running
        self._start_button.setEnabled(True)
        self._start_button.setText("Остановить" if running else START_TEXT)
        # Пока идёт подбор, главное действие — не запуск, и кнопка не должна кричать.
        wanted = "" if running else "Primary"
        if self._start_button.objectName() != wanted:
            self._start_button.setObjectName(wanted)
            self._start_button.style().unpolish(self._start_button)
            self._start_button.style().polish(self._start_button)
        for chip in [*self._service_chips, self._dpi_chip, self._add_targets]:
            chip.setEnabled(not running)
        self._stop_early.setEnabled(not running and self._current_mode() == "services")
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

    def _strategy_done(self, score: StrategyScore) -> None:
        self._add_row(score)
        if not score.is_baseline:
            self._done += 1
        self._show_timing()

    def _show_timing(self) -> None:
        self._timing.setText(
            timing(
                time.monotonic() - self._started_at,
                self._done,
                self._planned,
                self._early_run,
            )
        )

    def _stop_clock(self) -> None:
        self._clock.stop()
        self._timing.hide()

    def _finish(self, report: Report) -> None:
        self._report = report
        built, self._built = self._built, None
        self._set_running(False)
        self._progress.hide()
        took = clock(time.monotonic() - self._started_at)
        self._stop_clock()
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

        if built is None:
            self._offer_merge(report)
        else:
            self._judge_merged(report, built, suffix)

        path = save_report(report)
        self._status.setStyleSheet(f"color: {COLORS['text_muted']};")
        self._status.setText(f"Заняло {took}. Отчёт сохранён: {path.name}")

        # С галочкой человек просил не таблицу, а рабочий обход: найденное включаем.
        if self._early_run and not report.cancelled and best is not None and (
            repair.fully_works(best, coverage.uncovered_target_names())
        ):
            self._apply_best()
            self._verdict.setText(self._verdict.text() + f" «{best.name}» включена.")

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

    def _judge_merged(self, report: Report, built: StrategySpec, suffix: str) -> None:
        """Оставляет сборку в списке, только если она лучше исходных."""
        if merge.is_improvement(report, built.name):
            self._verdict.setStyleSheet(f"color: {COLORS['success']};")
            self._verdict.setText(
                f"Сборка лучше исходных: «{built.name}» теперь есть в списке стратегий."
            )
            return

        self._discard_merged(built)
        self._verdict.setStyleSheet(f"color: {COLORS['warning']};")
        self._verdict.setText(
            "Сборка не оказалась лучше исходных, поэтому в список стратегий не добавлена."
            + suffix
        )

    @staticmethod
    def _discard_merged(built: StrategySpec) -> None:
        built.path.unlink(missing_ok=True)

    def _fail(self, message: str) -> None:
        if self._built is not None:
            self._discard_merged(self._built)
            self._built = None
        self._set_running(False)
        self._start_button.setEnabled(True)
        self._progress.hide()
        self._stop_clock()
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

        composition = merge.compose(plan, specs, merge.service_hosts())
        self._merge_button.setVisible(False)
        if not composition.argv:
            self._verdict.setStyleSheet(f"color: {COLORS['warning']};")
            self._verdict.setText(
                "Совместить не получится: эти сервисы обслуживает одна и та же секция "
                "стратегии, и для неё можно выбрать только один способ обхода."
            )
            return

        path = merge.save(composition.argv, plan)
        built = strategies.load_one(path.stem)
        if built is None:
            path.unlink(missing_ok=True)
            self.controller.error.emit("Собранная стратегия не разобралась, она не сохранена.")
            return

        # Сборка меряется последней: при равном результате выиграет исходная.
        self._built = built
        self._launch([*specs, built], "services", self._selected_services())

        note = f"Заменено секций: {len(composition.swapped)}, основа: «{composition.base}»."
        if composition.conflicts:
            note += " Без своего способа обхода: " + ", ".join(composition.conflicts) + "."
        self._verdict.setText(f"{note} Проверяю, лучше ли сборка исходных…")

    def _apply_best(self) -> None:
        if self._report is None or self._report.best is None:
            return
        name = self._report.best.name
        self.controller.select_strategy(name)
        self.controller.stop()
        self.controller.start()
        self._status.setText(f"Применена стратегия «{name}»")
