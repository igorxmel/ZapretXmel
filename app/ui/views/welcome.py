"""Экран первоначальной настройки.

Показывается один раз, при первом запуске. Его задача — довести до состояния,
в котором обходом можно пользоваться: поставить ядро, выбрать стратегию и, если
нужен Telegram, поднять прокси. Без него первый запуск встречает пользователя
пустым дашбордом, по которому непонятно, с чего начинать.

Шаги не блокируют друг друга: любой можно пропустить и вернуться к нему позже
из обычных разделов — окно только подсказывает порядок.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import coreinfo, location, paths, shortcut, strategies, telegram
from app.core.updater import github
from app.ui.frameless import FramelessWindow
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, Divider, banner_pixmap
from app.ui.workers import CoreUpdateWorker, Task

log = logging.getLogger(__name__)


class Step(QWidget):
    """Один шаг настройки: что это, в каком оно состоянии и что нажать."""

    def __init__(self, number: int, title: str, hint: str, action: str, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, SPACE["sm"], 0, SPACE["sm"])
        layout.setSpacing(SPACE["md"])

        self._mark = QLabel(str(number))
        self._mark.setFixedWidth(22)
        self._mark.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._mark.setStyleSheet(f"color: {COLORS['text_muted']}; font-weight: 600;")
        layout.addWidget(self._mark)

        column = QVBoxLayout()
        column.setSpacing(2)

        self._title = QLabel(title)
        self._title.setStyleSheet("font-weight: 600;")
        column.addWidget(self._title)

        self._hint = QLabel(hint)
        self._hint.setObjectName("Dim")
        self._hint.setWordWrap(True)
        column.addWidget(self._hint)

        layout.addLayout(column, 1)

        self.button = QPushButton(action)
        layout.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignTop)

    def set_state(self, done: bool, hint: str, action: str, enabled: bool = True) -> None:
        self._mark.setText("✓" if done else self._mark.text().replace("✓", "•"))
        self._mark.setStyleSheet(
            f"color: {COLORS['success'] if done else COLORS['text_muted']}; font-weight: 600;"
        )
        self._hint.setText(hint)
        self.button.setText(action)
        self.button.setEnabled(enabled)


class WelcomeWindow(FramelessWindow):
    """Окно первого запуска."""

    finished = pyqtSignal()
    navigate = pyqtSignal(str)

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__("Знакомство", compact=True)
        self.controller = controller
        self._task: Task | None = None
        self._worker: CoreUpdateWorker | None = None

        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        # Ширина фиксированная, высота подбирается под содержимое: пояснения
        # к шагам переносятся по словам, и при жёсткой высоте нижние строки
        # обрезало.
        self.setFixedWidth(680)
        self.setMinimumHeight(640)

        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(SPACE["xxl"], SPACE["xl"], SPACE["xxl"], SPACE["xl"])
        layout.setSpacing(SPACE["md"])

        banner = QLabel()
        banner.setPixmap(banner_pixmap(420))
        banner.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(banner)

        subtitle = QLabel(
            "Обход блокировок без батников и консоли. Осталось три шага — "
            "любой можно пропустить и вернуться к нему позже."
        )
        subtitle.setObjectName("Dim")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addSpacing(SPACE["sm"])
        layout.addWidget(self._build_steps(), 1)

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._status)

        self._finish_button = QPushButton("Перейти к программе")
        self._finish_button.setObjectName("Primary")
        self._finish_button.clicked.connect(self._finish)
        layout.addWidget(self._finish_button)

        layout.addWidget(self._build_shortcut())
        layout.addWidget(self._build_location())

    def _build_shortcut(self) -> QWidget:
        """Предлагает ярлык: иначе программу потом негде искать.

        Установщика нет, в меню «Пуск» её тоже нет — это один файл там, куда
        его положили. Галочка стоит заранее: отказаться проще, чем вспомнить
        о ней через неделю.
        """
        box = QCheckBox("Создать ярлык на рабочем столе")
        box.setChecked(paths.is_frozen())
        box.setEnabled(paths.is_frozen())
        if not paths.is_frozen():
            box.setToolTip("Доступно в собранной версии: из исходников ярлык вёл бы на python")
        box.toggled.connect(self._toggle_shortcut)

        self._shortcut_box = box
        return box

    def _toggle_shortcut(self, wanted: bool) -> None:
        # Ярлык создаётся сразу, а не по кнопке «Перейти к программе»: так
        # видно результат, и окно можно закрыть любым способом.
        if not paths.is_frozen():
            return
        if wanted:
            self._say("Ярлык создан" if shortcut.create() else "Не удалось создать ярлык")
        else:
            shortcut.remove()

    def _build_location(self) -> QWidget:
        """Говорит, куда программа складывает ядро и настройки, и даёт сменить место.

        Без этого человек не знает, где окажутся полсотни мегабайт: папка
        берётся рядом с исполняемым файлом, и если его запустили из «Загрузок»,
        всё приземлится туда же. До установки ядра сменить место дешевле всего —
        переносить ещё нечего.
        """
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE["sm"])

        self._location_label = QLabel()
        self._location_label.setObjectName("Muted")
        self._location_label.setWordWrap(True)
        row.addWidget(self._location_label, 1)

        change = QPushButton("Выбрать…")
        change.setObjectName("Ghost")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(self._choose_location)
        row.addWidget(change)

        self._show_location()
        return container

    def _show_location(self) -> None:
        where = "рядом с программой" if paths.is_portable() else "в выбранной папке"
        self._location_label.setText(f"Ядро и настройки лягут {where}: {paths.install_root()}")

    def _choose_location(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Куда складывать ядро и настройки",
            str(paths.install_root()),
        )
        if not chosen:
            return

        target = Path(chosen)
        reason = location.check_target(target)
        if reason:
            self._say(reason, COLORS["danger"])
            return

        try:
            result = location.relocate(target)
        except Exception as error:  # noqa: BLE001 — причину показываем пользователю
            log.exception("Не удалось выбрать папку установки")
            self._say(str(error), COLORS["danger"])
            return

        self._show_location()
        self._say(f"Папка установки: {result.target}", COLORS["success"])

        # Программа переехала вместе с данными — работающий файл остался по
        # прежнему пути, и продолжать в нём нельзя.
        if result.executable:
            shortcut.retarget(result.executable)
            location.restart(result.executable)
            QApplication.quit()
            return

        self.controller.refresh()
        self.refresh()

    def _build_steps(self) -> Card:
        card = Card()
        body = card.body()

        self._core_step = Step(
            1,
            "Ядро zapret",
            "Официальная сборка Flowseal — её скачает и поставит приложение.",
            "Установить",
        )
        self._core_step.button.clicked.connect(self._install_core)
        body.addWidget(self._core_step)
        body.addWidget(Divider())

        self._strategy_step = Step(
            2,
            "Стратегия обхода",
            "Подбирается перебором: программа проверит сервисы и выберет рабочую.",
            "Подобрать",
        )
        self._strategy_step.button.clicked.connect(lambda: self._go("autopick"))
        body.addWidget(self._strategy_step)
        body.addWidget(Divider())

        self._telegram_step = Step(
            3,
            "Telegram (по желанию)",
            "Клиент Telegram чинится не стратегией, а отдельным локальным прокси.",
            "Настроить",
        )
        self._telegram_step.button.clicked.connect(lambda: self._go("telegram"))
        body.addWidget(self._telegram_step)

        body.addStretch(1)
        return card

    # --- состояние -------------------------------------------------------

    def refresh(self) -> None:
        core = coreinfo.describe()
        self._core_step.set_state(
            done=core.present,
            hint=(
                f"Установлена версия {core.version}, стратегий {core.strategy_count}."
                if core.present
                else "Официальная сборка Flowseal — её скачает и поставит приложение."
            ),
            action="Переустановить" if core.present else "Установить",
        )

        selected = self.controller.settings.selected_strategy
        has_strategy = bool(selected) and strategies.load_one(selected) is not None
        self._strategy_step.set_state(
            done=has_strategy,
            hint=(
                f"Выбрана стратегия «{selected}». Её можно сменить в любой момент."
                if has_strategy
                else "Подбирается перебором: программа проверит сервисы и выберет рабочую."
            ),
            action="Подобрать заново" if has_strategy else "Подобрать",
            enabled=core.present,
        )

        installed = telegram.is_installed()
        self._telegram_step.set_state(
            done=installed,
            hint=(
                "Прокси установлен — включить его можно с главного экрана."
                if installed
                else "Клиент Telegram чинится не стратегией, а отдельным локальным прокси."
            ),
            action="Открыть" if installed else "Настроить",
        )

    # --- действия --------------------------------------------------------

    def _install_core(self) -> None:
        self._core_step.button.setEnabled(False)
        self._say("Спрашиваю GitHub о последнем релизе…")

        self._task = Task(github.latest_release)
        self._task.done.connect(self._download_core)
        self._task.failed.connect(self._fail)
        self._task.start()

    def _download_core(self, release: github.Release) -> None:
        self._say(f"Скачиваю сборку {release.version}…")
        paths.ensure_dirs()

        self._worker = CoreUpdateWorker(release, paths.downloads_dir())
        self._worker.progress.connect(self._say)
        self._worker.done.connect(self._core_installed)
        self._worker.failed.connect(self._fail)
        self._worker.start()

    def _core_installed(self, version: str) -> None:
        self._core_step.button.setEnabled(True)
        self._say(f"Готово: установлена версия {version}", COLORS["success"])
        self.controller.refresh()
        self.refresh()

    def _go(self, destination: str) -> None:
        """Отправляет в нужный раздел и закрывает знакомство."""
        self.navigate.emit(destination)
        self._finish()

    def _finish(self) -> None:
        settings = self.controller.settings
        settings.first_run_done = True
        settings.save()
        self.finished.emit()
        self.close()

    def _say(self, text: str, colour: str = COLORS["text_muted"]) -> None:
        self._status.setStyleSheet(f"color: {colour};")
        self._status.setText(text)

    def _fail(self, message: str) -> None:
        self._core_step.button.setEnabled(True)
        self._say(message, COLORS["danger"])
