"""Экран настроек: режим запуска, игровой фильтр, IP-набор, фейки, автозапуск."""

from __future__ import annotations

import contextlib
import logging
import sys
import winreg
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core import fakes, gamefilter, ipset, location, paths, shortcut, uninstall
from app.core.gamefilter import GameFilter
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, Divider, KeyValueRow, view_header
from app.ui.workers import Task

log = logging.getLogger(__name__)

RUN_MODES = {
    "Служба Windows": "service",
    "Обычный процесс": "process",
}

# Про автозапуск легко ошибиться: в режиме службы обход и так поднимается
# вместе с Windows, и галочки здесь нужны только ради окна.
AUTOSTART_HINTS = {
    "service": (
        "Обход в режиме службы и так стартует вместе с Windows — даже до входа "
        "в систему и без запущенного приложения. Эти галочки нужны только для "
        "самого окна и значка в трее."
    ),
    "process": (
        "В режиме обычного процесса обход живёт вместе с приложением. Чтобы он "
        "поднимался сам, включите обе галочки: запуск с Windows и включение обхода."
    ),
}

RUN_MODE_HINTS = {
    "service": "Обход работает и без запущенного приложения, стартует вместе с системой.",
    "process": "Обход живёт, пока открыто приложение, зато виден его вывод в разделе «Логи».",
}

GAME_MODES = {
    "Выключен": "disabled",
    "TCP и UDP": "all",
    "Только TCP": "tcp",
    "Только UDP": "udp",
}

IPSET_MODES = {
    "Любые адреса": "any",
    "По списку": "loaded",
    "Выключен": "none",
}

IPSET_HINTS = {
    "any": "Обход применяется ко всему трафику на портах стратегии. Самый широкий режим.",
    "loaded": "Обход работает только по адресам из скачанного списка.",
    "none": "Фильтр по адресам не применяется — работают только списки доменов.",
}

AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE = "ZapretXmel"


class SettingsView(QWidget):
    """Настройки приложения и параметры сборки zapret."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._loading = False
        self._relocate_task: Task | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Настройки",
                "Игровой фильтр и IP-набор хранятся в файлах самой сборки, "
                "поэтому консольное меню апстрима видит те же значения.",
            )
        )

        right = QVBoxLayout()
        right.setSpacing(SPACE["lg"])
        right.addWidget(self._build_bundle_card())
        right.addWidget(self._build_uninstall_card())
        right.addStretch(1)

        left = QVBoxLayout()
        left.setSpacing(SPACE["lg"])
        left.addWidget(self._build_app_card())
        left.addWidget(self._build_checks_card())
        left.addStretch(1)

        columns = QHBoxLayout()
        columns.setSpacing(SPACE["lg"])
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)

        # Настроек больше, чем влезает в невысокое окно, и без прокрутки Qt
        # сжимает карточки ниже их собственной высоты: подписи наползают на
        # галочки, а нижняя кнопка обрезается рамкой.
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addLayout(columns)
        page_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        layout.addWidget(scroll, 1)

    def _build_app_card(self) -> Card:
        card = Card("Приложение")
        body = card.body()

        body.addWidget(QLabel("Как запускать обход"))
        self._run_mode = QComboBox()
        self._run_mode.addItems(RUN_MODES.keys())
        self._run_mode.currentIndexChanged.connect(self._save_run_mode)
        body.addWidget(self._run_mode)

        self._run_mode_hint = QLabel("")
        self._run_mode_hint.setObjectName("Muted")
        self._run_mode_hint.setWordWrap(True)
        body.addWidget(self._run_mode_hint)

        self._autostart = QCheckBox("Запускать приложение вместе с Windows")
        self._autostart.toggled.connect(self._toggle_autostart)
        body.addWidget(self._autostart)

        self._start_bypass = QCheckBox("Включать обход при запуске приложения")
        self._start_bypass.toggled.connect(self._save_flags)
        body.addWidget(self._start_bypass)

        self._autostart_hint = QLabel("")
        self._autostart_hint.setObjectName("Muted")
        self._autostart_hint.setWordWrap(True)
        body.addWidget(self._autostart_hint)

        self._start_proxy = QCheckBox("Включать прокси для Telegram при запуске")
        self._start_proxy.setToolTip(
            "Прокси работает дочерним процессом программы: своей службы у него "
            "нет, и сам с Windows он не стартует"
        )
        self._start_proxy.toggled.connect(self._save_flags)
        body.addWidget(self._start_proxy)

        self._start_minimized = QCheckBox("Запускать свёрнутым в трей")
        self._start_minimized.toggled.connect(self._save_flags)
        body.addWidget(self._start_minimized)

        self._minimize_to_tray = QCheckBox("Сворачивать в трей вместо закрытия")
        self._minimize_to_tray.toggled.connect(self._save_flags)
        body.addWidget(self._minimize_to_tray)

        self._notify_updates = QCheckBox("Сообщать о новых версиях")
        self._notify_updates.setToolTip(
            "Программа, ядро zapret и прокси для Telegram проверяются один раз "
            "при запуске. Обновляется всё равно вручную, в разделе «Обновления»."
        )
        self._notify_updates.toggled.connect(self._save_flags)
        body.addWidget(self._notify_updates)

        body.addWidget(Divider())

        # Куда всё складывается — вопрос, который возникает у каждого: по
        # умолчанию папка берётся рядом с исполняемым файлом, то есть чаще
        # всего в «Загрузках». Это стоит и показать, и дать сменить.
        self._folder_row = KeyValueRow("Папка установки")
        body.addWidget(self._folder_row)

        self._folder_hint = QLabel("")
        self._folder_hint.setObjectName("Muted")
        self._folder_hint.setWordWrap(True)
        body.addWidget(self._folder_hint)

        folder_buttons = QHBoxLayout()
        folder_buttons.setSpacing(SPACE["sm"])

        open_folder = QPushButton("Открыть папку")
        open_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.install_root())))
        )
        folder_buttons.addWidget(open_folder)

        change_folder = QPushButton("Сменить папку…")
        change_folder.clicked.connect(self._change_install_folder)
        folder_buttons.addWidget(change_folder)

        body.addLayout(folder_buttons)

        # Ярлыки — единственный способ найти программу потом: установщика
        # нет, сама она никуда не прописывается, а файл лежит там, куда его
        # положили.
        self._shortcut = QCheckBox("Ярлык на рабочем столе")
        self._shortcut.toggled.connect(self._toggle_shortcut)
        body.addWidget(self._shortcut)

        self._start_menu = QCheckBox("В меню «Пуск» — чтобы находилась поиском Windows")
        self._start_menu.setToolTip(
            "Поиск в «Пуске» просматривает папку с ярлыками программ. "
            "Пока нас там нет, набрать «zapret» и запустить не получится."
        )
        self._start_menu.toggled.connect(self._toggle_start_menu)
        body.addWidget(self._start_menu)

        body.addWidget(Divider())

        welcome = QPushButton("Показать окно знакомства")
        welcome.setToolTip("То самое окно с шагами настройки, что открывается при первом запуске")
        welcome.clicked.connect(self._show_welcome)
        body.addWidget(welcome)

        body.addStretch(1)
        return card

    def _build_checks_card(self) -> Card:
        """Сторож и то, с какими сроками идут проверки.

        Отдельной карточкой, а не вперемешку с запуском и папкой: это
        настройки одного занятия — проверки сервисов, — и теми же числами
        пользуется кнопка «Проверить, работает ли сейчас».
        """
        card = Card("Проверки")
        body = card.body()

        # Проверка идёт один раз, через минуту после запуска, и молчит, если
        # всё свежее. Но и это кому-то лишнее — пусть выключается.
        # Сторож гоняет те же проверки, что и кнопка на главном экране,
        # только сам и по таймеру.
        self._watch = QCheckBox("Следить, работает ли обход")
        self._watch.setToolTip(
            "Раз в несколько минут проверяет те же сервисы и сообщает, если "
            "что-то перестало открываться"
        )
        self._watch.toggled.connect(self._save_flags)
        body.addWidget(self._watch)

        watch_row = QHBoxLayout()
        watch_row.setSpacing(SPACE["sm"])
        watch_row.addWidget(QLabel("Проверять раз в, минут"))

        self._watch_interval = QSpinBox()
        self._watch_interval.setRange(1, 240)
        self._watch_interval.valueChanged.connect(self._save_flags)
        watch_row.addWidget(self._watch_interval)
        watch_row.addStretch(1)
        body.addLayout(watch_row)

        self._watch_autoswitch = QCheckBox("Переключать на следующую избранную стратегию")
        self._watch_autoswitch.setToolTip(
            "Если обход сломался, сторож попробует другую стратегию из избранного. "
            "Перебирать все подряд он не станет — для этого есть подбор."
        )
        self._watch_autoswitch.toggled.connect(self._save_flags)
        body.addWidget(self._watch_autoswitch)

        body.addWidget(QLabel("Таймаут одной проверки, секунд"))
        self._timeout = QSpinBox()
        self._timeout.setRange(2, 30)
        self._timeout.valueChanged.connect(self._save_flags)
        body.addWidget(self._timeout)

        body.addWidget(QLabel("Сколько целей проверять одновременно"))
        self._parallel = QSpinBox()
        self._parallel.setRange(1, 32)
        self._parallel.valueChanged.connect(self._save_flags)
        body.addWidget(self._parallel)

        return card

    def _build_uninstall_card(self) -> Card:
        """Удаление того, что программа принесла на компьютер.

        Установщика у неё нет, в «Программах и компонентах» её не найти —
        значит, убирать за собой она должна сама, иначе после стирания .exe
        в системе остаются служба, драйвер и сотня мегабайт ядра.
        """
        card = Card("Удаление")
        body = card.body()

        note = QLabel(
            "Удаление идёт сразу и без корзины. Ядро и прокси потом "
            "ставятся заново из программы."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        body.addWidget(note)

        remove_core = QPushButton("Удалить ядро zapret")
        remove_core.setToolTip("Служба Windows, процессы winws, папка ядра и бэкапы")
        remove_core.clicked.connect(lambda: self._remove("core"))
        body.addWidget(remove_core)

        remove_proxy = QPushButton("Удалить прокси для Telegram")
        remove_proxy.setToolTip("Папка tgproxy вместе с настройками прокси")
        remove_proxy.clicked.connect(lambda: self._remove("proxy"))
        body.addWidget(remove_proxy)

        remove_all = QPushButton("Удалить все данные программы")
        remove_all.setObjectName("Danger")
        remove_all.setToolTip("Ядро, прокси, настройки, журналы и ярлык")
        remove_all.clicked.connect(lambda: self._remove("all"))
        body.addWidget(remove_all)

        return card

    def _build_bundle_card(self) -> Card:
        card = Card("Параметры сборки")
        body = card.body()

        body.addWidget(QLabel("Игровой фильтр"))
        self._game_mode = QComboBox()
        self._game_mode.addItems(GAME_MODES.keys())
        self._game_mode.currentIndexChanged.connect(self._save_game_filter)
        body.addWidget(self._game_mode)

        ranges = QHBoxLayout()
        ranges.setSpacing(SPACE["sm"])
        self._game_tcp = QLineEdit()
        self._game_tcp.setPlaceholderText("Диапазон TCP, например 1024-65535")
        self._game_udp = QLineEdit()
        self._game_udp.setPlaceholderText("Диапазон UDP")
        ranges.addWidget(self._game_tcp)
        ranges.addWidget(self._game_udp)
        body.addLayout(ranges)

        apply_ranges = QPushButton("Сохранить диапазоны")
        apply_ranges.clicked.connect(self._save_game_filter)
        body.addWidget(apply_ranges)

        self._game_hint = QLabel("")
        self._game_hint.setObjectName("Muted")
        self._game_hint.setWordWrap(True)
        body.addWidget(self._game_hint)

        body.addWidget(QLabel("Фильтр по IP-адресам"))
        self._ipset_mode = QComboBox()
        self._ipset_mode.addItems(IPSET_MODES.keys())
        self._ipset_mode.currentIndexChanged.connect(self._save_ipset)
        body.addWidget(self._ipset_mode)

        self._ipset_hint = QLabel("")
        self._ipset_hint.setObjectName("Muted")
        self._ipset_hint.setWordWrap(True)
        body.addWidget(self._ipset_hint)

        body.addWidget(QLabel("Активные фейковые пакеты"))
        self._fake_slot = QComboBox()
        self._fake_source = QComboBox()
        fake_row = QHBoxLayout()
        fake_row.setSpacing(SPACE["sm"])
        fake_row.addWidget(self._fake_slot, 1)
        fake_row.addWidget(self._fake_source, 1)
        body.addLayout(fake_row)

        replace_button = QPushButton("Заменить фейк")
        replace_button.clicked.connect(self._replace_fake)
        body.addWidget(replace_button)

        body.addStretch(1)
        return card

    # --- загрузка и сохранение ------------------------------------------

    def reload(self) -> None:
        self._loading = True
        try:
            settings = self.controller.settings

            self._select_by_value(self._run_mode, RUN_MODES, settings.run_mode)
            self._run_mode_hint.setText(RUN_MODE_HINTS[settings.run_mode])
            self._autostart_hint.setText(AUTOSTART_HINTS[settings.run_mode])
            self._autostart.setChecked(autostart_enabled())
            self._start_bypass.setChecked(settings.start_bypass_on_launch)
            self._start_proxy.setChecked(settings.start_proxy_on_launch)
            self._start_minimized.setChecked(settings.start_minimized)
            self._minimize_to_tray.setChecked(settings.minimize_to_tray)
            self._notify_updates.setChecked(settings.notify_updates)
            self._watch.setChecked(settings.watch_enabled)
            self._watch_interval.setValue(settings.watch_interval_minutes)
            self._watch_autoswitch.setChecked(settings.watch_autoswitch)
            self._watch_interval.setEnabled(settings.watch_enabled)
            self._watch_autoswitch.setEnabled(settings.watch_enabled)
            self._folder_row.set_value(str(paths.install_root()))
            self._shortcut.setChecked(shortcut.exists())
            self._start_menu.setChecked(shortcut.exists(shortcut.START_MENU))
            self._shortcut.setEnabled(paths.is_frozen())
            self._shortcut.setToolTip(
                ""
                if paths.is_frozen()
                else "Доступно в собранной версии: из исходников ярлык вёл бы на интерпретатор"
            )
            self._folder_hint.setText(
                "Здесь лежат ядро zapret, настройки, логи и бэкапы."
                + (
                    " Сейчас это папка рядом с программой: перенести всё можно,"
                    " просто перенеся её целиком."
                    if paths.is_portable()
                    else " Сама программа при этом осталась в своей папке."
                )
            )
            self._timeout.setValue(settings.probe_timeout)
            self._parallel.setValue(settings.probe_parallel)

            game = gamefilter.load()
            self._select_by_value(self._game_mode, GAME_MODES, game.mode)
            self._game_tcp.setText(game.tcp_range)
            self._game_udp.setText(game.udp_range)
            self._game_hint.setText(
                "При выключенном фильтре в стратегию подставляется порт-заглушка 12 — "
                "так секция не задевает реальный трафик."
            )

            current_ipset = ipset.status()
            self._select_by_value(self._ipset_mode, IPSET_MODES, current_ipset)
            self._ipset_hint.setText(IPSET_HINTS[current_ipset])
            self._reload_fakes()
        finally:
            self._loading = False
        self._relocate_task: Task | None = None

    def _reload_fakes(self) -> None:
        self._fake_slot.clear()
        for slot in fakes.slots():
            label = f"{slot.title} — сейчас {slot.current or 'не задан'}"
            self._fake_slot.addItem(label, slot.filename)

        self._fake_source.clear()
        for path in fakes.available():
            self._fake_source.addItem(path.stem, path.stem)

    @staticmethod
    def _select_by_value(combo: QComboBox, mapping: dict[str, str], value: str) -> None:
        for index, key in enumerate(mapping):
            if mapping[key] == value:
                combo.setCurrentIndex(index)
                return

    # --- место установки ------------------------------------------------

    def _change_install_folder(self) -> None:
        """Спрашивает новую папку и переносит в неё установку."""
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
            self._refuse_folder(reason)
            return

        if not self._confirm_relocation(target):
            return

        self._relocate_task = Task(self.controller.relocate, target)
        self._relocate_task.done.connect(self._relocated)
        self._relocate_task.failed.connect(self.controller.error.emit)
        self._relocate_task.start()
        self._folder_hint.setText(f"Переношу установку в {target}…")

    def _relocated(self, moved_to) -> None:
        """Завершает переезд: обновляет ярлык и перезапускает программу.

        Перезапуск не предлагается, а выполняется: файл .exe уже лежит в
        новой папке, а работающий процесс помнит прежний путь и писал бы
        данные туда, где программы больше нет.
        """
        self.reload()
        if not moved_to:
            return

        shortcut.retarget(moved_to)
        self._folder_hint.setText(f"Программа переехала в {moved_to.parent}, перезапускаю…")

        try:
            location.restart(moved_to)
        except Exception as error:  # noqa: BLE001 — причину показываем пользователю
            self.controller.error.emit(str(error))
            return

        QApplication.quit()

    def _toggle_shortcut(self, wanted: bool) -> None:
        self._toggle_link(shortcut.DESKTOP, wanted)

    def _toggle_start_menu(self, wanted: bool) -> None:
        self._toggle_link(shortcut.START_MENU, wanted)

    def _toggle_link(self, where: str, wanted: bool) -> None:
        if self._loading:
            return

        title = shortcut.TITLES[where]
        if wanted:
            ok = shortcut.create(where=where)
            self.controller.message.emit(
                f"Создан {title}" if ok else f"Не удалось создать {title}"
            )
        else:
            shortcut.remove(where)
            self.controller.message.emit(f"Удалён {title}")

    def _refuse_folder(self, reason: str) -> None:
        refusal = QMessageBox(self)
        refusal.setWindowTitle("Папка не подходит")
        refusal.setIcon(QMessageBox.Icon.Warning)
        refusal.setText(reason)
        refusal.addButton("Понятно", QMessageBox.ButtonRole.AcceptRole)
        refusal.exec()

    def _confirm_relocation(self, target: Path) -> bool:
        """Переезд останавливает обход и трогает сотню мегабайт — спросим прямо."""
        size = location.installed_size_mb()
        free = location.free_space_mb(target)

        question = QMessageBox(self)
        question.setWindowTitle("Сменить папку установки")
        question.setIcon(QMessageBox.Icon.Question)
        question.setText(f"Перенести ядро и настройки в {target}?")
        details = [
            f"Переносится {size} МБ, на диске свободно {free} МБ.",
            "Программа переедет вместе с данными и перезапустится оттуда — "
            "в прежней папке не останется ничего.",
            "Обход выключится на время переноса и включится заново: служба "
            "помнит полный путь к winws.exe, и после переезда её нужно поставить снова.",
        ]
        if free and size > free:
            details.insert(1, "Места на диске может не хватить.")
        question.setInformativeText("\n\n".join(details))

        move = question.addButton("Перенести", QMessageBox.ButtonRole.AcceptRole)
        question.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        question.exec()

        return question.clickedButton() is move

    # --- удаление --------------------------------------------------------

    def _remove(self, what: str) -> None:
        """Убирает ядро, прокси или всё сразу — после прямого подтверждения."""
        titles = {
            "core": ("ядро zapret", "Будут сняты служба и процессы winws, удалены папка "
                     "ядра и бэкапы. Стратегии и свои списки тоже исчезнут."),
            "proxy": ("прокси для Telegram", "Прокси будет остановлен, его папка удалена. "
                      "В настройках самого Telegram он останется прописанным — "
                      "уберите его там вручную."),
            "all": ("все данные программы", "Будет удалено всё: ядро, прокси, настройки, "
                    "журналы и ярлык."),
        }
        title, details = titles[what]

        question = QMessageBox(self)
        question.setWindowTitle("Удаление")
        question.setIcon(QMessageBox.Icon.Warning)
        question.setText(f"Удалить {title}?")

        if what == "all":
            details += "\n\nОстанется: " + ", ".join(uninstall.leftovers()) + "."
        question.setInformativeText(details + "\n\nОтменить это нельзя.")

        confirm = question.addButton("Удалить", QMessageBox.ButtonRole.DestructiveRole)
        question.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        question.exec()

        if question.clickedButton() is not confirm:
            return

        actions = {
            "core": uninstall.remove_core,
            "proxy": uninstall.remove_proxy,
            "all": uninstall.remove_everything,
        }
        # Снятие службы ходит в `sc`, а папка ядра — это сотня мегабайт:
        # в потоке интерфейса окно замерло бы до конца удаления.
        self._remove_task = Task(actions[what])
        self._remove_task.done.connect(lambda result: self._removed(what, result))
        self._remove_task.failed.connect(self.controller.error.emit)
        self._remove_task.start()
        self.controller.message.emit(f"Удаляю {title}…")

    def _removed(self, what: str, result: uninstall.Removed) -> None:
        self.controller.message.emit(f"Удаление: {result.summary}")
        self.controller.refresh()
        self.reload()

        if what == "all":
            self._say_goodbye()

    def _say_goodbye(self) -> None:
        """Объясняет, что осталось сделать руками, и закрывает программу."""
        farewell = QMessageBox(self)
        farewell.setWindowTitle("Готово")
        farewell.setIcon(QMessageBox.Icon.Information)
        farewell.setText("Данные программы удалены.")
        farewell.setInformativeText(
            f"Осталось стереть сам файл {paths.executable().name} — работающую "
            "программу Windows удалить не даёт, а делать это за вас после выхода "
            "мы не станем: так ведут себя ровно те программы, от которых защищают "
            "антивирусы.\n\nСейчас программа закроется."
        )
        farewell.addButton("Закрыть", QMessageBox.ButtonRole.AcceptRole)
        farewell.exec()

        QApplication.quit()

    def _show_welcome(self) -> None:
        # Окно знакомства живёт в главном окне: оно модальное и должно
        # перекрывать всё приложение, а не один экран настроек.
        window = self.window()
        if hasattr(window, "show_welcome"):
            window.show_welcome()

    def _save_run_mode(self) -> None:
        if self._loading:
            return
        mode = RUN_MODES[self._run_mode.currentText()]
        self.controller.settings.run_mode = mode
        self.controller.settings.save()
        self._run_mode_hint.setText(RUN_MODE_HINTS[mode])
        self._autostart_hint.setText(AUTOSTART_HINTS[mode])
        self.controller.message.emit("Режим запуска изменится при следующем включении обхода")

    def _save_flags(self) -> None:
        if self._loading:
            return
        settings = self.controller.settings
        settings.start_bypass_on_launch = self._start_bypass.isChecked()
        settings.start_proxy_on_launch = self._start_proxy.isChecked()
        settings.start_minimized = self._start_minimized.isChecked()
        settings.minimize_to_tray = self._minimize_to_tray.isChecked()
        settings.notify_updates = self._notify_updates.isChecked()
        settings.watch_enabled = self._watch.isChecked()
        settings.watch_interval_minutes = self._watch_interval.value()
        settings.watch_autoswitch = self._watch_autoswitch.isChecked()
        self._watch_interval.setEnabled(settings.watch_enabled)
        self._watch_autoswitch.setEnabled(settings.watch_enabled)
        settings.probe_timeout = self._timeout.value()
        settings.probe_parallel = self._parallel.value()
        settings.save()

        # Таймер сторожа живёт в контроллере и должен узнать о новой частоте
        # сразу, а не после перезапуска программы.
        self.controller.restart_watch()

    def _toggle_autostart(self, enabled: bool) -> None:
        if self._loading:
            return
        if set_autostart(enabled):
            self.controller.settings.autostart_with_windows = enabled
            self.controller.settings.save()
        else:
            self.controller.error.emit("Не удалось изменить автозапуск")

    def _save_game_filter(self) -> None:
        if self._loading:
            return

        mode = GAME_MODES[self._game_mode.currentText()]
        tcp = gamefilter.validate_range(self._game_tcp.text()) or gamefilter.DEFAULT_RANGE
        udp = gamefilter.validate_range(self._game_udp.text()) or gamefilter.DEFAULT_RANGE

        for label, field in (("TCP", self._game_tcp), ("UDP", self._game_udp)):
            raw = field.text().strip()
            if raw and gamefilter.validate_range(raw) is None:
                self.controller.error.emit(
                    f"Диапазон {label} указан неверно — пример: 1024-65535"
                )
                return

        gamefilter.save(GameFilter(mode=mode, tcp_range=tcp, udp_range=udp))
        self._game_tcp.setText(tcp)
        self._game_udp.setText(udp)
        self.controller.message.emit(
            "Игровой фильтр сохранён. Перезапустите обход, чтобы он применился."
        )

    def _save_ipset(self) -> None:
        if self._loading:
            return
        mode = IPSET_MODES[self._ipset_mode.currentText()]
        try:
            ipset.set_mode(mode)
        except FileNotFoundError as error:
            self.controller.error.emit(str(error))
            self.reload()
            return

        self._ipset_hint.setText(IPSET_HINTS[mode])
        self.controller.message.emit(f"Режим IP-набора: {ipset.LABELS[mode]}")

    def _replace_fake(self) -> None:
        slot = self._fake_slot.currentData()
        source = self._fake_source.currentData()
        if not slot or not source:
            return
        try:
            fakes.replace(slot, source)
        except (FileNotFoundError, ValueError, OSError) as error:
            self.controller.error.emit(str(error))
            return

        self._reload_fakes()
        self.controller.message.emit(
            f"Активный фейк заменён на {source}. Перезапустите обход."
        )
        self._game_hint.setStyleSheet(f"color: {COLORS['text_muted']};")


# --- автозапуск ---------------------------------------------------------


def _autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script = Path(sys.argv[0]).resolve()
    return f'"{sys.executable}" "{script}"'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
            winreg.QueryValueEx(key, AUTOSTART_VALUE)
            return True
    except (FileNotFoundError, OSError):
        return False


def set_autostart(enabled: bool) -> bool:
    """Добавляет или убирает запись автозапуска для текущего пользователя."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(key, AUTOSTART_VALUE, 0, winreg.REG_SZ, _autostart_command())
            else:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, AUTOSTART_VALUE)
        return True
    except OSError:
        log.warning("Не удалось изменить автозапуск")
        return False
