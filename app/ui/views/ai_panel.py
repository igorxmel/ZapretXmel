"""Панель разбора нейросетью.

Живёт на экране диагностики рядом с проверками по правилам. Правила ловят
известное и работают всегда; сюда обращаются за тем, чего в правилах нет.

Выгрузка пакета намеренно не требует ключа: это основной путь для тех, кто не
хочет ничего подключать, — забрал архив и отдал любому чат-боту.
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
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.core.diagnostics import ai, bundle, secrets, snapshot
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, Divider
from app.ui.workers import Task

log = logging.getLogger(__name__)


class AiPanel(QWidget):
    """Описание проблемы, выбор сервиса и разбор."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._task: Task | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(self._build_card(), 1)

    def _build_card(self) -> Card:
        card = Card("Разбор нейросетью")
        body = card.body()

        hint = QLabel(
            "Проверки слева ловят известные причины. Нейросеть нужна для случаев, "
            "которых в них нет: странный лог, непонятное сочетание настроек."
        )
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        body.addWidget(hint)

        body.addWidget(QLabel("Что не работает"))
        self._problem = QPlainTextEdit()
        self._problem.setPlaceholderText(
            "Например: Discord не подключается, висит на Connecting. YouTube работает."
        )
        self._problem.setMaximumHeight(70)
        body.addWidget(self._problem)

        body.addWidget(Divider())

        export_row = QHBoxLayout()
        export_row.setSpacing(SPACE["sm"])

        export = QPushButton("Выгрузить пакет для любого ИИ")
        export.setObjectName("Primary")
        export.setToolTip(
            "Архив с данными, пояснением к ним и готовым запросом — "
            "ключ не нужен, отдать можно любому чат-боту"
        )
        export.clicked.connect(self._export)
        export_row.addWidget(export)
        export_row.addStretch(1)
        body.addLayout(export_row)

        body.addWidget(Divider())

        body.addWidget(QLabel("Или разобрать прямо здесь"))

        choose = QHBoxLayout()
        choose.setSpacing(SPACE["sm"])

        self._provider = QComboBox()
        for provider in ai.PROVIDERS:
            self._provider.addItem(provider.label, provider.id)
        self._provider.currentIndexChanged.connect(self._provider_changed)
        choose.addWidget(self._provider, 1)

        self._model = QComboBox()
        choose.addWidget(self._model, 1)

        # Список моделей зашивать нельзя: сервисы снимают их с обслуживания,
        # и разбор начинает отвечать «404» вместо ответа.
        self._refresh_models = QPushButton("Обновить")
        self._refresh_models.setToolTip(
            "Спросить у сервиса, какие модели у него есть сейчас"
        )
        self._refresh_models.clicked.connect(self._load_models)
        choose.addWidget(self._refresh_models)
        body.addLayout(choose)

        self._provider_note = QLabel("")
        self._provider_note.setObjectName("Muted")
        self._provider_note.setWordWrap(True)
        body.addWidget(self._provider_note)

        key_row = QHBoxLayout()
        key_row.setSpacing(SPACE["sm"])

        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("Ключ доступа")
        key_row.addWidget(self._key, 1)

        save_key = QPushButton("Сохранить")
        save_key.clicked.connect(self._save_key)
        key_row.addWidget(save_key)

        get_key = QPushButton("Где взять")
        get_key.setObjectName("Ghost")
        get_key.setCursor(Qt.CursorShape.PointingHandCursor)
        get_key.clicked.connect(self._open_key_page)
        key_row.addWidget(get_key)
        body.addLayout(key_row)

        self._analyze_button = QPushButton("Разобрать")
        self._analyze_button.clicked.connect(self._analyze)
        body.addWidget(self._analyze_button)

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        body.addWidget(self._status)

        self._answer = QTextBrowser()
        self._answer.setPlaceholderText("Здесь появится разбор")
        body.addWidget(self._answer, 1)

        return card

    # --- состояние -------------------------------------------------------

    def reload(self) -> None:
        self._provider_changed()

    def _current_provider(self) -> ai.Provider:
        provider = ai.provider_by_id(self._provider.currentData())
        return provider or ai.PROVIDERS[0]

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
        self._provider_note.setText(note)
        self._analyze_button.setEnabled(True)

    def _load_models(self) -> None:
        """Спрашивает у сервиса список моделей.

        Ключ берётся сохранённый или только что введённый: без него
        большинство сервисов список не отдаёт.
        """
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

    # --- действия --------------------------------------------------------

    def _export(self) -> None:
        self._say("Собираю пакет…")
        problem = self._problem.toPlainText()

        self._task = Task(bundle.export, problem=problem)
        self._task.done.connect(self._exported)
        self._task.failed.connect(self._fail)
        self._task.start()

    def _exported(self, path) -> None:
        self._say(f"Готово: {path.name}", COLORS["success"])
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        self.controller.message.emit(
            "Пакет собран. Внутри — данные, пояснение и готовый запрос: "
            "отдайте архив любому чат-боту целиком."
        )

    def _save_key(self) -> None:
        provider = self._current_provider()
        value = self._key.text().strip()
        try:
            secrets.save(ai.key_name(provider.id), value)
        except OSError as error:
            self._fail(str(error))
            return

        self._say(
            f"Ключ для {provider.label} сохранён" if value else "Ключ удалён",
            COLORS["success"],
        )
        self._provider_changed()

    def _open_key_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self._current_provider().key_url))

    def _analyze(self) -> None:
        provider = self._current_provider()
        if not ai.has_key(provider.id):
            self._say(
                f"Для {provider.label} не сохранён ключ. Либо сохраните его, "
                "либо выгрузите пакет — он работает без ключа.",
                COLORS["warning"],
            )
            return

        self._analyze_button.setEnabled(False)
        self._say(f"Спрашиваю {provider.label}… это занимает до минуты")
        problem = self._problem.toPlainText()
        model = self._model.currentText()

        self._task = Task(self._run, provider.id, model, problem)
        self._task.done.connect(self._show_answer)
        self._task.failed.connect(self._fail)
        self._task.start()

    @staticmethod
    def _run(provider_id: str, model: str, problem: str) -> ai.Analysis:
        return ai.analyze(snapshot.build(), problem, provider_id, model)

    def _show_answer(self, analysis: ai.Analysis) -> None:
        self._analyze_button.setEnabled(True)
        self._say(f"{analysis.provider} · {analysis.model}", COLORS["text_muted"])

        if analysis.is_empty and analysis.raw:
            self._answer.setPlainText(analysis.raw)
            return
        self._answer.setPlainText(analysis.as_text())

    def _say(self, text: str, colour: str = COLORS["text_muted"]) -> None:
        self._status.setStyleSheet(f"color: {colour};")
        self._status.setText(text)

    def _fail(self, message: str) -> None:
        self._analyze_button.setEnabled(True)
        self._say(message, COLORS["danger"])
