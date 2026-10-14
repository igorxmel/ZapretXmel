"""Экран профилей приложений.

Позволяет пропустить через обход конкретную программу — игру, клиент, что
угодно. Про ограничение сказано прямо на экране: winws не умеет фильтровать по
процессу, поэтому фильтр выводится из того, куда приложение ходит.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core import appprofile
from app.core.appprofile import Profile, Recorder
from app.ui.controller import Controller, Status
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, Divider, view_header

log = logging.getLogger(__name__)

SAMPLE_INTERVAL_MS = 1000

LIMITS = (
    "Как это работает: winws не умеет фильтровать по процессу — такого поля нет "
    "на том уровне, где он перехватывает пакеты. Поэтому программа смотрит, куда "
    "ходит выбранное приложение, и собирает фильтр по его портам и адресам.\n\n"
    "Отсюда следствия: другое приложение, которое пойдёт на те же адреса и порты, "
    "попадёт под те же правила; игры с меняющимся пулом серверов потребуют "
    "повторной записи. Профиль работает отдельным процессом и основную стратегию "
    "не трогает."
)


class ProfilesView(QWidget):
    """Запись трафика приложения и включение собранного профиля."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._recorder: Recorder | None = None
        self._profiles: list[Profile] = []

        self._timer = QTimer(self)
        self._timer.setInterval(SAMPLE_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Профили приложений",
                "Пропустить через обход отдельную программу — игру или клиент, "
                "которому не помогают обычные стратегии.",
            )
        )

        columns = QHBoxLayout()
        columns.setSpacing(SPACE["lg"])
        columns.addWidget(self._build_record_card(), 1)
        columns.addWidget(self._build_profiles_card(), 1)
        layout.addLayout(columns, 1)

        controller.status_changed.connect(self._apply_status)

    def _build_record_card(self) -> Card:
        card = Card("Запись")
        body = card.body()

        hint = QLabel(
            "Выберите программу, нажмите «Записывать» и попользуйтесь ей пару минут — "
            "зайдите в игру, подключитесь к голосовому каналу. Чем дольше запись, "
            "тем полнее фильтр."
        )
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        body.addWidget(hint)

        self._apps = QListWidget()
        body.addWidget(self._apps, 1)

        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])

        refresh = QPushButton("Обновить список")
        refresh.clicked.connect(self.reload)
        row.addWidget(refresh)

        self._record_button = QPushButton("Записывать")
        self._record_button.setObjectName("Primary")
        self._record_button.clicked.connect(self._toggle_record)
        row.addWidget(self._record_button)
        row.addStretch(1)
        body.addLayout(row)

        threshold = QHBoxLayout()
        threshold.setSpacing(SPACE["sm"])
        threshold.addWidget(QLabel("Отсекать адреса, замеченные реже чем"))
        self._min_hits = QSpinBox()
        self._min_hits.setRange(1, 20)
        self._min_hits.setValue(2)
        self._min_hits.setToolTip(
            "В записи оседает телеметрия и проверки обновлений — им в фильтре не место"
        )
        threshold.addWidget(self._min_hits)
        threshold.addWidget(QLabel("раз"))
        threshold.addStretch(1)
        body.addLayout(threshold)

        self._record_status = QLabel("")
        self._record_status.setObjectName("Muted")
        self._record_status.setWordWrap(True)
        body.addWidget(self._record_status)

        return card

    def _build_profiles_card(self) -> Card:
        card = Card("Сохранённые профили")
        body = card.body()

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._sync_buttons)
        body.addWidget(self._list, 1)

        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])

        self._apply_button = QPushButton("Включить")
        self._apply_button.setObjectName("Primary")
        self._apply_button.clicked.connect(self._apply_profile)
        row.addWidget(self._apply_button)

        self._stop_button = QPushButton("Выключить")
        self._stop_button.clicked.connect(self.controller.stop_profile)
        row.addWidget(self._stop_button)

        self._delete_button = QPushButton("Удалить")
        self._delete_button.setObjectName("Danger")
        self._delete_button.clicked.connect(self._delete_profile)
        row.addWidget(self._delete_button)
        row.addStretch(1)
        body.addLayout(row)

        body.addWidget(Divider())

        limits = QLabel(LIMITS)
        limits.setObjectName("Muted")
        limits.setWordWrap(True)
        body.addWidget(limits)

        return card

    # --- данные ---------------------------------------------------------

    def reload(self) -> None:
        if self._recorder is None:
            self._apps.clear()
            for app in appprofile.running_apps():
                item = QListWidgetItem(app.label)
                item.setData(Qt.ItemDataRole.UserRole, app.pid)
                self._apps.addItem(item)

        self._reload_profiles()

    def _reload_profiles(self) -> None:
        self._profiles = appprofile.load_all()
        active = self.controller.status.active_profile

        self._list.clear()
        for profile in self._profiles:
            mark = " ● работает" if profile.name == active else ""
            self._list.addItem(f"{profile.name} — {profile.summary}{mark}")

        self._sync_buttons()

    def _current_profile(self) -> Profile | None:
        row = self._list.currentRow()
        return self._profiles[row] if 0 <= row < len(self._profiles) else None

    def _sync_buttons(self) -> None:
        profile = self._current_profile()
        running = bool(self.controller.status.active_profile)
        self._apply_button.setEnabled(profile is not None)
        self._delete_button.setEnabled(profile is not None)
        self._stop_button.setEnabled(running)

    def _apply_status(self, status: Status) -> None:
        self._stop_button.setEnabled(bool(status.active_profile))

    # --- запись ---------------------------------------------------------

    def _toggle_record(self) -> None:
        if self._recorder is not None:
            self._finish_record()
            return

        item = self._apps.currentItem()
        if item is None:
            self.controller.error.emit("Выберите программу из списка.")
            return

        self._recorder = Recorder(item.data(Qt.ItemDataRole.UserRole))
        self._record_button.setText("Остановить запись")
        self._apps.setEnabled(False)
        self._timer.start()
        self._say("Записываю… попользуйтесь программой.")

    def _tick(self) -> None:
        if self._recorder is None:
            return
        self._recorder.refresh_tree()
        self._recorder.sample()
        self._say(f"Записываю… точек найдено: {len(self._recorder.seen)}")

    def _finish_record(self) -> None:
        self._timer.stop()
        recorder, self._recorder = self._recorder, None
        self._record_button.setText("Записывать")
        self._apps.setEnabled(True)

        if recorder is None:
            return

        if not recorder.seen:
            self._say(
                "Ничего не записалось. Возможно, программа не обращалась в сеть "
                "или её соединения не видны без прав администратора.",
                COLORS["warning"],
            )
            return

        name, ok = QInputDialog.getText(self, "Сохранить профиль", "Название профиля:")
        if not ok or not name.strip():
            self._say("Запись отброшена.")
            return

        profile = appprofile.build_profile(
            name.strip(),
            recorder.endpoints,
            min_hits=self._min_hits.value(),
            counts=recorder.seen,
        )
        if profile.is_empty:
            self._say(
                "После отсева ничего не осталось — попробуйте снизить порог "
                "или записать дольше.",
                COLORS["warning"],
            )
            return

        appprofile.save(profile)
        self._say(f"Профиль «{profile.name}» сохранён: {profile.summary}", COLORS["success"])
        self._reload_profiles()

    # --- применение -----------------------------------------------------

    def _apply_profile(self) -> None:
        profile = self._current_profile()
        if profile is not None:
            self.controller.start_profile(profile)
            self._reload_profiles()

    def _delete_profile(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        if profile.name == self.controller.status.active_profile:
            self.controller.stop_profile()
        appprofile.delete(profile.name)
        self._reload_profiles()

    def _say(self, text: str, colour: str = COLORS["text_muted"]) -> None:
        self._record_status.setStyleSheet(f"color: {colour};")
        self._record_status.setText(text)
