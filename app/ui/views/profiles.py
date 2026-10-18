"""Экран профилей приложений.

Позволяет пропустить через обход конкретную программу — игру, клиент, что
угодно. Про ограничение сказано прямо на экране: winws не умеет фильтровать по
процессу, поэтому фильтр выводится из того, куда приложение ходит.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
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
from app.ui import dialogs
from app.ui.controller import Controller, Status
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.views.profileedit import ProfileEditor
from app.ui.widgets import Card, Divider, view_header

log = logging.getLogger(__name__)

SAMPLE_INTERVAL_MS = 1000

# Как часто перечитывать список запущенных программ, пока экран открыт.
APPS_REFRESH_MS = 3000

# Вопрос «а как оно вообще понимает, что игра запустилась» возникает у всех,
# поэтому ответ висит прямо на галочке, а не в документации.
AUTO_START_HINT = (
    "Программа каждые несколько секунд смотрит список запущенных процессов и "
    "ищет тот .exe, с которого профиль записан. Появился — профиль включается, "
    "исчез — выключается.\n\n"
    "Сравнивается путь к файлу, а не имя процесса и не его номер: номер у "
    "каждого запуска свой, а game.exe в двух разных установках — это две "
    "разные программы. Если путь не совпал (игру перенесли или обновил "
    "лаунчер), остаётся запасная сверка по имени файла.\n\n"
    "Выключается только то, что включилось само: профиль, поднятый руками, "
    "останется работать — вы могли оставить его намеренно."
)

LIMITS = (
    "Как это работает: winws не умеет фильтровать по процессу — такого поля нет "
    "на том уровне, где он перехватывает пакеты. Поэтому программа смотрит, куда "
    "ходит выбранное приложение, и собирает фильтр по его портам и адресам.\n\n"
    "Профилей можно держать включёнными сколько угодно: каждый работает своим "
    "процессом. Но если два профиля ловят одни и те же порты, пакет пройдёт "
    "через оба — лучше так не делать.\n\n"
    "Отсюда следствия: другое приложение, которое пойдёт на те же адреса и порты, "
    "попадёт под те же правила; игры с меняющимся пулом серверов потребуют "
    "повторной записи. Основную стратегию профили не трогают."
)


class ProfilesView(QWidget):
    """Запись трафика приложения и включение собранного профиля."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._recorder: Recorder | None = None
        self._recorded_exe = ""
        self._shown_active: tuple = ()

        # Список запущенных программ живёт своей жизнью: его обновляем, пока
        # экран открыт, а не только при переходе на него.
        self._apps_timer = QTimer(self)
        self._apps_timer.setInterval(APPS_REFRESH_MS)
        self._apps_timer.timeout.connect(self._refresh_apps)
        self._profiles: list[Profile] = []
        # Пока подставляем значения в галочку, её сигнал не должен
        # перезаписывать профиль.
        self._loading = False

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
        self._stop_button.clicked.connect(self._stop_profile)
        row.addWidget(self._stop_button)

        self._edit_button = QPushButton("Посмотреть и править")
        self._edit_button.setToolTip("Что внутри профиля: приложение, порты, адреса")
        self._edit_button.clicked.connect(self._edit_profile)
        row.addWidget(self._edit_button)

        self._new_button = QPushButton("Создать вручную")
        self._new_button.setToolTip(
            "Если порты и адреса известны заранее — записывать трафик незачем"
        )
        self._new_button.clicked.connect(self._new_profile)
        row.addWidget(self._new_button)

        self._delete_button = QPushButton("Удалить")
        self._delete_button.setObjectName("Danger")
        self._delete_button.clicked.connect(self._delete_profile)
        row.addWidget(self._delete_button)
        row.addStretch(1)
        body.addLayout(row)

        # Профиль включают перед игрой и забывают выключить — или не включают
        # вовсе и потом удивляются, почему снова лагает.
        self._auto_start = QCheckBox("Включать вместе с приложением")
        self._auto_start.setToolTip(AUTO_START_HINT)
        self._auto_start.toggled.connect(self._save_auto_start)
        body.addWidget(self._auto_start)

        body.addWidget(Divider())

        limits = QLabel(LIMITS)
        limits.setObjectName("Muted")
        limits.setWordWrap(True)
        body.addWidget(limits)

        return card

    # --- данные ---------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        """Пока экран открыт, список приложений обновляется сам.

        Программу для записи обычно запускают уже после того, как открыли
        этот экран, — и она не появлялась в списке до перехода на другую
        вкладку и обратно.
        """
        super().showEvent(event)
        self._apps_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        super().hideEvent(event)
        self._apps_timer.stop()

    def _refresh_apps(self) -> None:
        """Перечитывает список, сохраняя выбор.

        Во время записи не трогаем: выбранная программа не должна уехать
        из-под курсора, пока идёт запись её трафика.
        """
        if self._recorder is not None:
            return

        chosen = self._apps.currentItem()
        wanted = chosen.data(Qt.ItemDataRole.UserRole) if chosen else None

        self._apps.clear()
        for app in appprofile.running_apps():
            item = QListWidgetItem(app.label)
            item.setData(Qt.ItemDataRole.UserRole, app.pid)
            item.setData(Qt.ItemDataRole.UserRole + 1, app.exe)
            self._apps.addItem(item)
            if app.pid == wanted:
                self._apps.setCurrentItem(item)

    def reload(self) -> None:
        if self._recorder is None:
            self._apps.clear()
            for app in appprofile.running_apps():
                item = QListWidgetItem(app.label)
                item.setData(Qt.ItemDataRole.UserRole, app.pid)
                item.setData(Qt.ItemDataRole.UserRole + 1, app.exe)
                self._apps.addItem(item)

        self._reload_profiles()

    def _reload_profiles(self) -> None:
        """Перерисовывает список, сохраняя выбор.

        Раньше здесь был просто `clear()`, и выделение слетало после каждого
        включения: человек нажимал «Включить», профиль пропадал из выбора, а
        кнопки гасли — будто что-то сломалось.
        """
        chosen = self._selected_name()
        self._profiles = appprofile.load_all()
        active = self.controller.status.active_profiles

        # Работающий профиль — наверх: он единственный, к кому есть вопросы
        # прямо сейчас, а искать его в списке по десятку имён неудобно.
        self._profiles.sort(
            key=lambda profile: (profile.name not in active, profile.name.lower())
        )

        self._list.clear()
        for profile in self._profiles:
            running = profile.name in active
            item = QListWidgetItem(self._profile_label(profile, running))
            if running:
                item.setForeground(QColor(COLORS["success"]))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self._list.addItem(item)

        self._restore_selection(chosen)
        self._sync_buttons()

    @staticmethod
    def _profile_label(profile: Profile, running: bool) -> str:
        """Строка профиля: имя, приложение и состав фильтра.

        Приложение показывается здесь, а не только в правке: профиль — это
        фильтр по портам и адресам, и без имени программы через неделю уже
        не вспомнить, к чему он относится.
        """
        head = f"{profile.name} ● работает" if running else profile.name
        app = Path(profile.exe).name if profile.exe else "приложение не записано"
        return f"{head}\n{app} · {profile.summary}"

    def _selected_name(self) -> str:
        profile = self._current_profile()
        return profile.name if profile else ""

    def _restore_selection(self, name: str) -> None:
        for row, profile in enumerate(self._profiles):
            if profile.name == name:
                self._list.setCurrentRow(row)
                return
        if self._profiles:
            self._list.setCurrentRow(0)

    def _current_profile(self) -> Profile | None:
        row = self._list.currentRow()
        return self._profiles[row] if 0 <= row < len(self._profiles) else None

    def _sync_buttons(self) -> None:
        profile = self._current_profile()
        active = self.controller.status.active_profiles
        # Включать уже включённый незачем: кнопка оставалась живой, и нажатие
        # поднимало второй экземпляр winws поверх первого.
        this_one_runs = bool(profile and profile.name in active)

        self._apply_button.setEnabled(profile is not None and not this_one_runs)
        self._apply_button.setText("Работает" if this_one_runs else "Включить")
        self._delete_button.setEnabled(profile is not None)
        self._edit_button.setEnabled(profile is not None)
        self._stop_button.setEnabled(this_one_runs)

        self._auto_start.setEnabled(profile is not None and bool(profile.exe))
        self._auto_start.setToolTip(
            AUTO_START_HINT
            if profile is None or profile.exe
            else "В профиле не записан путь к приложению — следить не за чем. "
            "Запишите профиль заново или укажите приложение в правке."
        )
        self._loading = True
        try:
            self._auto_start.setChecked(bool(profile and profile.auto_start))
        finally:
            self._loading = False

    def _save_auto_start(self, wanted: bool) -> None:
        """Запоминает выбор в самом профиле — он переживает перезапуск."""
        if self._loading:
            return

        profile = self._current_profile()
        if profile is None:
            return

        profile.auto_start = wanted
        appprofile.save(profile)
        self._say(
            f"Профиль «{profile.name}» будет включаться вместе с приложением"
            if wanted
            else f"Профиль «{profile.name}» включается только вручную"
        )

    def _apply_status(self, status: Status) -> None:
        """Следит за состоянием, не дожидаясь возврата на экран.

        Профиль гасится и снаружи — кнопкой «Выключить», сторожем приложений,
        закрытием самой игры. Без этого список врал до перехода на другую
        вкладку и обратно.
        """
        if status.active_profiles != self._shown_active:
            self._shown_active = status.active_profiles
            self._reload_profiles()
            return
        self._sync_buttons()

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
        # Путь к приложению нужен профилю: по нему сторож потом узнаёт, что
        # приложение запустилось. Без него галочка «включать вместе с
        # приложением» оставалась серой — включать было нечего.
        self._recorded_exe = item.data(Qt.ItemDataRole.UserRole + 1) or ""
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

        name = dialogs.ask_text(
            self,
            "Сохранить профиль",
            "Как назвать профиль?",
            f"Записано точек: {len(recorder.seen)}. Имя нужно только для списка — "
            "подойдёт название игры или клиента.",
            value=Path(self._recorded_exe).stem if self._recorded_exe else "",
            placeholder="например, roblox",
        )
        if not name:
            self._say("Запись отброшена.")
            return

        profile = appprofile.build_profile(
            name,
            recorder.endpoints,
            exe=self._recorded_exe,
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

    def _stop_profile(self) -> None:
        """Гасит профиль и говорит, что он сам больше не поднимется.

        С галочкой «включать вместе с приложением» и запущенной игрой
        профиль возвращался через пару секунд, и кнопка выглядела
        неработающей.
        """
        profile = self._current_profile()
        if profile is None:
            return
        self.controller.stop_profile(profile.name, by_hand=True)

        if profile is not None and profile.auto_start:
            self._say(
                f"Профиль «{profile.name}» выключен и сам больше не включится — "
                "до следующего запуска приложения.",
                COLORS["warning"],
            )

    def _edit_profile(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        self._open_editor(profile)

    def _new_profile(self) -> None:
        self._open_editor(Profile(name=""), is_new=True)

    def _open_editor(self, profile: Profile, is_new: bool = False) -> None:
        """Открывает правку и сохраняет результат.

        Переименование — это новый файл: старый надо убрать, иначе в списке
        окажутся два профиля с одним составом и разными именами.
        """
        editor = ProfileEditor(self, profile, is_new=is_new)
        editor.ask()
        if editor.saved is None:
            return

        saved = editor.saved
        appprofile.save(saved)
        if not is_new and saved.name != profile.name:
            appprofile.delete(profile.name)

        self._reload_profiles()
        self._restore_selection(saved.name)
        self._sync_buttons()
        self._say(f"Профиль «{saved.name}» сохранён: {saved.summary}", COLORS["success"])

    def _delete_profile(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        if profile.name in self.controller.status.active_profiles:
            self.controller.stop_profile(profile.name)
        appprofile.delete(profile.name)
        self._reload_profiles()

    def _say(self, text: str, colour: str = COLORS["text_muted"]) -> None:
        self._record_status.setStyleSheet(f"color: {colour};")
        self._record_status.setText(text)
