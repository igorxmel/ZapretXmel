"""Отдельное окно разбора неполадки нейросетью.

Раньше разбор жил половиной экрана диагностики и не помещался туда ни с
какой стороны: названия моделей вроде `meta-llama/llama-3.3-70b-instruct`
обрезались в узком списке, а ответ на несколько абзацев читался в окошке
высотой в пять строк.

Здесь места хватает всему: выбор сервиса и модели во всю ширину, большой
ответ и список прошлых разборов слева. Последнее — не украшение: человек
спрашивает, пробует совет, спрашивает снова, и сравнить с прошлым ответом
иначе негде.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from app.core.diagnostics import ai, aihistory, secrets, snapshot
from app.ui.frameless import FramelessWindow
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, Divider
from app.ui.workers import Task

log = logging.getLogger(__name__)

WIDTH = 1040
HEIGHT = 720
HISTORY_WIDTH = 260


class AiWindow(FramelessWindow):
    """Разбор нейросетью: выбор сервиса, вопрос, ответ и прошлые разборы."""

    def __init__(self, parent: QWidget | None = None):
        # Растягивать нужно: ответ бывает длинным, а экраны — разными.
        super().__init__("Разбор нейросетью", compact=True, resizable=True)
        self.resize(WIDTH, HEIGHT)
        self.setMinimumSize(760, 520)

        self._task: Task | None = None
        self._models_task: Task | None = None

        layout = QHBoxLayout(self.body)
        layout.setContentsMargins(SPACE["lg"], 0, SPACE["lg"], SPACE["lg"])
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(self._build_history(), 0)
        layout.addWidget(self._build_main(), 1)

        self._provider_changed()
        self._reload_history()

    # --- разметка --------------------------------------------------------

    def _build_history(self) -> Card:
        card = Card("Прошлые разборы")
        card.setFixedWidth(HISTORY_WIDTH)
        body = card.body()

        self._history = QListWidget()
        self._history.currentRowChanged.connect(self._show_from_history)
        body.addWidget(self._history, 1)

        clear = QPushButton("Очистить")
        clear.clicked.connect(self._clear_history)
        body.addWidget(clear)

        return card

    def _build_main(self) -> Card:
        card = Card("Запрос")
        body = card.body()

        choose = QHBoxLayout()
        choose.setSpacing(SPACE["sm"])

        self._provider = QComboBox()
        for provider in ai.PROVIDERS:
            self._provider.addItem(provider.label, provider.id)
        self._provider.currentIndexChanged.connect(self._provider_changed)
        choose.addWidget(self._provider)

        # Во всю оставшуюся ширину: названия моделей бывают длиннее самого
        # окна диагностики, где этот список стоял раньше.
        self._model = QComboBox()
        self._model.setMinimumWidth(320)
        choose.addWidget(self._model, 1)

        self._refresh_models = QPushButton("Обновить список")
        self._refresh_models.setToolTip("Спросить у сервиса, какие модели у него есть сейчас")
        self._refresh_models.clicked.connect(self._load_models)
        choose.addWidget(self._refresh_models)
        body.addLayout(choose)

        self._note = QLabel("")
        self._note.setObjectName("Muted")
        self._note.setWordWrap(True)
        body.addWidget(self._note)

        key_row = QHBoxLayout()
        key_row.setSpacing(SPACE["sm"])
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        key_row.addWidget(self._key, 1)

        save_key = QPushButton("Сохранить ключ")
        save_key.clicked.connect(self._save_key)
        key_row.addWidget(save_key)

        where = QPushButton("Где взять")
        where.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(self._current_provider().key_url))
        )
        key_row.addWidget(where)
        body.addLayout(key_row)

        body.addWidget(Divider())

        body.addWidget(QLabel("Что не работает"))
        self._problem = QPlainTextEdit()
        self._problem.setPlaceholderText(
            "Например: Discord не подключается, висит на Connecting. YouTube работает."
        )
        self._problem.setFixedHeight(70)
        body.addWidget(self._problem)

        self._ask = QPushButton("Разобрать")
        self._ask.setObjectName("Primary")
        self._ask.clicked.connect(self._analyze)
        body.addWidget(self._ask)

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        body.addWidget(self._status)

        self._answer = QPlainTextEdit()
        self._answer.setReadOnly(True)
        self._answer.setPlaceholderText("Здесь появится разбор")
        body.addWidget(self._answer, 1)

        return card

    def set_problem(self, text: str) -> None:
        """Подставляет описание, набранное на экране диагностики."""
        self._problem.setPlainText(text)

    # --- сервис и модели -------------------------------------------------

    def _current_provider(self) -> ai.Provider:
        return ai.provider_by_id(self._provider.currentData()) or ai.PROVIDERS[0]

    def _provider_changed(self) -> None:
        provider = self._current_provider()

        self._model.clear()
        self._model.addItems(provider.models)

        saved = secrets.has(ai.key_name(provider.id))
        self._key.setPlaceholderText("Ключ сохранён" if saved else "Ключ доступа")
        self._key.clear()

        note = provider.note
        if not saved:
            note += " Ключ пока не сохранён."
        self._note.setText(note)

    def _load_models(self) -> None:
        provider = self._current_provider()
        key = self._key.text().strip() or secrets.load(ai.key_name(provider.id))
        if not key and provider.id != "openrouter":
            self._say(f"Сначала сохраните ключ для {provider.label}.", COLORS["warning"])
            return

        self._refresh_models.setEnabled(False)
        self._say(f"Спрашиваю у {provider.label} список моделей…")

        self._models_task = Task(ai.list_models, provider, key)
        self._models_task.done.connect(self._models_loaded)
        self._models_task.failed.connect(self._models_failed)
        self._models_task.start()

    def _models_loaded(self, names: list) -> None:
        self._refresh_models.setEnabled(True)
        if not names:
            self._say("Сервис не назвал ни одной модели.", COLORS["warning"])
            return

        chosen = self._model.currentText()
        self._model.clear()
        self._model.addItems(names)
        if chosen in names:
            self._model.setCurrentText(chosen)
        self._say(f"Моделей доступно: {len(names)}", COLORS["success"])

    def _models_failed(self, message: str) -> None:
        self._refresh_models.setEnabled(True)
        self._say(message, COLORS["danger"])

    def _save_key(self) -> None:
        provider = self._current_provider()
        try:
            secrets.save(ai.key_name(provider.id), self._key.text().strip())
        except OSError as error:
            self._say(str(error), COLORS["danger"])
            return

        self._say(f"Ключ для {provider.label} сохранён", COLORS["success"])
        self._provider_changed()

    # --- разбор ----------------------------------------------------------

    def _analyze(self) -> None:
        provider = self._current_provider()
        if not ai.has_key(provider.id):
            self._say(
                f"Для {provider.label} не сохранён ключ. Либо сохраните его, "
                "либо выгрузите пакет на экране диагностики — он работает без ключа.",
                COLORS["warning"],
            )
            return

        self._ask.setEnabled(False)
        self._say(f"Спрашиваю {provider.label}… это занимает до минуты")

        problem = self._problem.toPlainText()
        self._task = Task(self._run, provider.id, self._model.currentText(), problem)
        self._task.done.connect(lambda analysis: self._show_answer(analysis, problem))
        self._task.failed.connect(self._fail)
        self._task.start()

    @staticmethod
    def _run(provider_id: str, model: str, problem: str) -> ai.Analysis:
        return ai.analyze(snapshot.build(), problem, provider_id, model)

    def _show_answer(self, analysis: ai.Analysis, problem: str) -> None:
        self._ask.setEnabled(True)
        self._say(f"{analysis.provider} · {analysis.model}")

        if analysis.is_empty and analysis.raw:
            self._answer.setPlainText(analysis.raw)
        else:
            self._answer.setPlainText(analysis.as_text())

        aihistory.remember(analysis, problem)
        self._reload_history()

    def _fail(self, message: str) -> None:
        self._ask.setEnabled(True)
        self._say(message, COLORS["danger"])

    # --- история ---------------------------------------------------------

    def _reload_history(self) -> None:
        self._entries = aihistory.load()
        self._history.blockSignals(True)
        self._history.clear()
        for entry in self._entries:
            item = QListWidgetItem(entry.title)
            item.setToolTip(f"{entry.provider} · {entry.model}")
            self._history.addItem(item)
        self._history.blockSignals(False)

    def _show_from_history(self, row: int) -> None:
        if not 0 <= row < len(self._entries):
            return

        entry = self._entries[row]
        self._problem.setPlainText(entry.problem)
        self._say(f"{entry.provider} · {entry.model} · {entry.asked_at[:16].replace('T', ' ')}")

        parts = [entry.verdict, entry.cause]
        parts += [f"{number}. {step}" for number, step in enumerate(entry.steps, 1)]
        if entry.confidence:
            parts.append(f"Уверенность: {entry.confidence}")
        self._answer.setPlainText("\n\n".join(part for part in parts if part))

    def _clear_history(self) -> None:
        aihistory.clear()
        self._reload_history()
        self._answer.clear()
        self._say("История очищена")

    def _say(self, text: str, colour: str = COLORS["text_muted"]) -> None:
        self._status.setStyleSheet(f"color: {colour};")
        self._status.setText(text)

    def keyPressEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        """Esc закрывает окно: оно вспомогательное и открывается поверх."""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
