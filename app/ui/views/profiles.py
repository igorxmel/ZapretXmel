"""Экран профилей приложений.

Позволяет пропустить через обход конкретную программу — игру, клиент, что
угодно. Про ограничение сказано прямо на экране: winws не умеет фильтровать по
процессу, поэтому фильтр выводится из того, куда приложение ходит.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QFileInfo, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileIconProvider,
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
from app.ui.widgets import Card, IconButton, IconChip, SectionTitle, view_header

log = logging.getLogger(__name__)

SAMPLE_INTERVAL_MS = 1000

ICON_SIZE = 20
RECORD_TEXT = "Записывать"
EXE_ROLE = Qt.ItemDataRole.UserRole
PIDS_ROLE = Qt.ItemDataRole.UserRole + 1

MIN_HITS_HINT = (
    "Адреса, к которым программа обратилась реже этого числа раз за запись, в фильтр не "
    "попадут: обычно это телеметрия и проверки обновлений."
)

_icons: QFileIconProvider | None = None


def program_icon(exe: str) -> QIcon:
    """Значок самой программы — так её узнают быстрее, чем по имени файла."""
    global _icons
    if not exe or not Path(exe).is_file():
        return QIcon()
    if _icons is None:
        _icons = QFileIconProvider()
    return _icons.icon(QFileInfo(exe))


def program_tip(program: appprofile.Program) -> str:
    processes = len(program.pids)
    count = f"{processes} процесс" + ("" if processes == 1 else "а" if processes < 5 else "ов")
    return f"{program.exe}\n{count}, все попадут в запись"

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
        # Пояснения — за значком «i» у заголовка: на экране они стояли серыми
        # абзацами и закрывали собой то, что нужно нажимать.
        about = IconButton("info", "Как работают профили", size=24, icon_size=18)
        about.clicked.connect(
            lambda: dialogs.tell(self, "Профили приложений", "Как это работает", LIMITS)
        )
        layout.addWidget(
            view_header(
                "Профили приложений",
                "Пропустить через обход отдельную программу — игру или клиент, "
                "которому не помогают обычные стратегии.",
                aside=about,
            )
        )

        columns = QHBoxLayout()
        columns.setSpacing(SPACE["lg"])
        columns.addWidget(self._build_record_card(), 1)
        columns.addWidget(self._build_profiles_card(), 1)
        layout.addLayout(columns, 1)

        controller.status_changed.connect(self._apply_status)

    def _build_record_card(self) -> Card:
        card = Card("Записать программу")
        body = card.body()

        hint = QLabel("Выберите программу и попользуйтесь ей пару минут, пока идёт запись.")
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        body.addWidget(hint)

        # Одна строка на программу, со значком и названием из свойств файла. Список
        # по процессам показывал семь «Discord.exe (pid …)» подряд, и было непонятно,
        # какой выбирать. Обновляется сам, пока экран открыт.
        self._apps = QListWidget()
        self._apps.setObjectName("ProgramList")
        self._apps.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._apps.itemDoubleClicked.connect(lambda _item: self._toggle_record())
        body.addWidget(self._apps, 1)

        row = QHBoxLayout()
        row.setSpacing(SPACE["md"])
        self._record_button = QPushButton(RECORD_TEXT)
        self._record_button.setObjectName("Primary")
        self._record_button.clicked.connect(self._toggle_record)
        row.addWidget(self._record_button)
        row.addStretch(1)

        # Порог — тонкая настройка, нужна редко: компактно справа, пояснение в подсказке.
        rare = QLabel("Отсев редких адресов")
        rare.setObjectName("Muted")
        rare.setToolTip(MIN_HITS_HINT)
        row.addWidget(rare)
        self._min_hits = QSpinBox()
        self._min_hits.setRange(1, 20)
        self._min_hits.setValue(2)
        self._min_hits.setToolTip(MIN_HITS_HINT)
        row.addWidget(self._min_hits)
        body.addLayout(row)

        self._record_status = QLabel("")
        self._record_status.setObjectName("Muted")
        self._record_status.setWordWrap(True)
        body.addWidget(self._record_status)

        return card

    def _build_profiles_card(self) -> Card:
        card = Card()
        body = card.body()

        # Заголовок свой, а не из Card: справа от него «+» — создать профиль руками.
        head = QHBoxLayout()
        head.setSpacing(SPACE["sm"])
        head.addWidget(SectionTitle("Мои профили"))
        head.addStretch(1)
        self._new_button = IconChip(
            "plus", "Создать профиль вручную — если порты и адреса известны заранее"
        )
        self._new_button.clicked.connect(self._new_profile)
        head.addWidget(self._new_button)
        body.addLayout(head)

        self._list = QListWidget()
        self._list.setObjectName("ProgramList")
        self._list.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._list.currentRowChanged.connect(self._sync_buttons)
        self._list.itemDoubleClicked.connect(lambda _item: self._edit_profile())
        body.addWidget(self._list, 1)

        self._empty = QLabel(
            "Профилей пока нет. Запишите программу слева — профиль появится здесь."
        )
        self._empty.setObjectName("Muted")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(self._empty)

        # Пять кнопок в ряд не помещались при узком окне. Осталось главное действие,
        # правка и удаление значком; «Создать» — плюсом у заголовка.
        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])
        self._toggle_button = QPushButton("Включить")
        self._toggle_button.setObjectName("Primary")
        self._toggle_button.clicked.connect(self._toggle_profile)
        row.addWidget(self._toggle_button)

        self._edit_button = QPushButton("Изменить")
        self._edit_button.setToolTip("Что внутри профиля: приложение, порты, адреса")
        self._edit_button.clicked.connect(self._edit_profile)
        row.addWidget(self._edit_button)
        row.addStretch(1)

        self._delete_button = IconButton("trash", "Удалить профиль")
        self._delete_button.clicked.connect(self._delete_profile)
        row.addWidget(self._delete_button)
        body.addLayout(row)

        # Профиль включают перед игрой и забывают выключить — или не включают
        # вовсе и потом удивляются, почему снова лагает.
        self._auto_start = QCheckBox("Включать вместе с приложением")
        self._auto_start.setToolTip(AUTO_START_HINT)
        self._auto_start.toggled.connect(self._save_auto_start)
        body.addWidget(self._auto_start)

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
        wanted = chosen.data(EXE_ROLE) if chosen else None
        scrolled = self._apps.verticalScrollBar().value()

        self._apps.clear()
        for program in appprofile.running_programs():
            item = QListWidgetItem(program_icon(program.exe), program.title)
            item.setToolTip(program_tip(program))
            item.setData(EXE_ROLE, program.exe)
            item.setData(PIDS_ROLE, list(program.pids))
            self._apps.addItem(item)
            if program.exe == wanted:
                self._apps.setCurrentItem(item)
        self._apps.verticalScrollBar().setValue(scrolled)

    def reload(self) -> None:
        if self._recorder is None:
            self._refresh_apps()
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
        self._list.setVisible(bool(self._profiles))
        self._empty.setVisible(not self._profiles)
        for profile in self._profiles:
            running = profile.name in active
            item = QListWidgetItem(
                program_icon(profile.exe), self._profile_label(profile, running)
            )
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
        head = f"{profile.name}  ·  работает" if running else profile.name
        app = appprofile.display_name(profile.exe) if profile.exe else "приложение не указано"
        return f"{head}\n{app}"

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

        self._toggle_button.setEnabled(profile is not None)
        self._toggle_button.setText("Выключить" if this_one_runs else "Включить")
        # Включённый профиль — главное действие уже не «включить», кнопка не кричит.
        wanted = "" if this_one_runs else "Primary"
        if self._toggle_button.objectName() != wanted:
            self._toggle_button.setObjectName(wanted)
            self._toggle_button.style().unpolish(self._toggle_button)
            self._toggle_button.style().polish(self._toggle_button)
        self._delete_button.setEnabled(profile is not None)
        self._edit_button.setEnabled(profile is not None)

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

        # Путь к приложению нужен профилю: по нему сторож потом узнаёт, что
        # приложение запустилось. Без него галочка «включать вместе с
        # приложением» оставалась серой — включать было нечего.
        self._recorded_exe = item.data(EXE_ROLE) or ""
        # Все процессы программы и те, что она запустит во время записи.
        self._recorder = Recorder(item.data(PIDS_ROLE) or [], exe=self._recorded_exe)
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
        self._record_button.setText(RECORD_TEXT)
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

    def _toggle_profile(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        if profile.name in self.controller.status.active_profiles:
            self._stop_profile()
        else:
            self._apply_profile()

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
        if not dialogs.confirm(
            self,
            "Удалить профиль",
            f"Удалить профиль «{profile.name}»?",
            "Вернуть его можно только новой записью.",
            action="Удалить",
            danger=True,
        ):
            return
        if profile.name in self.controller.status.active_profiles:
            self.controller.stop_profile(profile.name)
        appprofile.delete(profile.name)
        self._reload_profiles()

    def _say(self, text: str, colour: str = COLORS["text_muted"]) -> None:
        self._record_status.setStyleSheet(f"color: {colour};")
        self._record_status.setText(text)
