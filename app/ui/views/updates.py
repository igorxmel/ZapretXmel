"""Экран обновлений: ядро, список IP-адресов и системный файл hosts."""

from __future__ import annotations

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.core import coreinfo, hosts, ipset, paths, telegram, updates
from app.core.updater import github, install, selfupdate
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, KeyValueRow, view_header
from app.ui.workers import AppUpdateWorker, CoreUpdateWorker, Task, TelegramInstallWorker

# Источники обновлений в общей карточке.
CORE = "core"
PROXY = "proxy"


class UpdatesView(QWidget):
    """Установка официальных релизов Flowseal и откат на предыдущую версию."""

    whats_new_requested = pyqtSignal()
    # Установка ядра и обновление программы идут десятками секунд: боковое
    # меню должно показывать, что работа ещё не кончилась.
    busy_changed = pyqtSignal(bool)
    # Что-то поставлено — полоса вверху окна о нём больше не актуальна.
    something_updated = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._latest: github.Release | None = None
        self._worker: CoreUpdateWorker | None = None
        self._task: Task | None = None
        self._install_after_check = False
        self._app_worker: AppUpdateWorker | None = None
        self._proxy_worker: TelegramInstallWorker | None = None
        self._proxy_task: Task | None = None
        self._source = CORE

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Обновления",
                "Ядро берётся только из официального репозитория Flowseal. "
                "Пользовательские списки переносятся в новую версию автоматически.",
            )
        )

        layout.addWidget(self._build_app_card())

        columns = QHBoxLayout()
        columns.setSpacing(SPACE["lg"])
        columns.addWidget(self._build_core_card(), 3)

        columns.addWidget(self._build_extras_card(), 2)
        layout.addLayout(columns, 1)

    def _build_app_card(self) -> Card:
        card = Card("Сама программа")
        body = card.body()

        row = QHBoxLayout()
        row.setSpacing(SPACE["md"])

        self._row_app = KeyValueRow("Версия программы")
        row.addWidget(self._row_app, 1)

        # Окно после обновления показывается один раз; посмотреть, что
        # изменилось, человек может захотеть и позже.
        self._whats_new = QPushButton("Что нового")
        self._whats_new.clicked.connect(self.whats_new_requested.emit)
        row.addWidget(self._whats_new)

        self._app_check = QPushButton("Проверить")
        self._app_check.clicked.connect(self._check_app)
        row.addWidget(self._app_check)

        self._app_install = QPushButton("Обновить и перезапустить")
        self._app_install.setObjectName("Primary")
        self._app_install.setEnabled(False)
        self._app_install.clicked.connect(self._update_app)
        row.addWidget(self._app_install)
        body.addLayout(row)

        self._app_status = QLabel("")
        self._app_status.setObjectName("Muted")
        self._app_status.setWordWrap(True)
        body.addWidget(self._app_status)

        self._app_progress = QProgressBar()
        self._app_progress.setRange(0, 100)
        self._app_progress.hide()
        body.addWidget(self._app_progress)

        return card

    # --- сама программа ---------------------------------------------------

    def _app_busy(self) -> bool:
        """Правда, если обновление уже идёт."""
        return self._app_worker is not None and self._app_worker.isRunning()

    def _check_app(self) -> None:
        # Пока идёт загрузка, проверять нечего: повторное нажатие включало
        # кнопку обновления обратно, вторая загрузка писала в тот же файл, и
        # обновление падало с ошибкой доступа.
        if self._app_busy():
            return

        if not selfupdate.is_frozen():
            self._app_say(
                "Программа запущена из исходников — обновлять нечего: "
                "здесь это делает git.",
                COLORS["text_muted"],
            )
            return

        self._app_check.setEnabled(False)
        self._app_say("Смотрю релизы программы…")
        self._task = Task(selfupdate.check)
        self._task.done.connect(self._app_checked)
        self._task.failed.connect(self._app_failed)
        self._task.start()

    def _app_checked(self, release) -> None:
        self._app_check.setEnabled(True)
        self._new_app = release

        if release is None:
            self._app_say("Установлена последняя версия программы", COLORS["success"])
            self._app_install.setEnabled(False)
            return

        self._app_install.setEnabled(True)
        self._app_say(
            f"Доступна версия {release.version} от {release.published_date}",
            COLORS["warning"],
        )

    def _update_app(self) -> None:
        release = getattr(self, "_new_app", None)
        if release is None or self._app_busy():
            return

        self._app_install.setEnabled(False)
        self._app_check.setEnabled(False)
        self._app_progress.setValue(0)
        self._app_progress.show()

        self.busy_changed.emit(True)
        self._app_worker = AppUpdateWorker(release)
        self._app_worker.progress.connect(self._app_say)
        self._app_worker.percent.connect(self._app_progress.setValue)
        self._app_worker.done.connect(self._app_updated)
        self._app_worker.failed.connect(self._app_failed)
        self._app_worker.start()

    def _app_updated(self, _result) -> None:
        self._app_progress.hide()
        self._app_say("Обновлено, перезапускаюсь…", COLORS["success"])
        try:
            selfupdate.restart()
        except selfupdate.SelfUpdateError as error:
            self._app_failed(str(error))
            return
        QApplication.quit()

    def _app_failed(self, message: str) -> None:
        self.busy_changed.emit(False)
        self._app_progress.hide()
        self._app_check.setEnabled(True)
        self._app_install.setEnabled(getattr(self, "_new_app", None) is not None)
        self._app_say(message, COLORS["danger"])

    def _app_say(self, text: str, colour: str = COLORS["text_muted"]) -> None:
        self._app_status.setStyleSheet(f"color: {colour};")
        self._app_status.setText(text)

    # --- ядро -----------------------------------------------------------

    def _build_core_card(self) -> Card:
        card = Card()
        body = card.body()

        # Переключатель источника. Ядро и прокси обновляются из разных
        # репозиториев, но выглядит это одинаково, поэтому и карточка одна.
        switch = QHBoxLayout()
        switch.setSpacing(SPACE["sm"])

        self._source_group = QButtonGroup(self)
        self._source_group.setExclusive(True)

        self._source_buttons: dict[str, QPushButton] = {}
        for key, title in (("core", "Ядро zapret"), ("proxy", "Прокси Telegram")):
            button = QPushButton(title)
            button.setObjectName("Chip")
            button.setCheckable(True)
            button.setChecked(key == CORE)
            button.clicked.connect(lambda _, source=key: self._switch_source(source))
            self._source_group.addButton(button)
            self._source_buttons[key] = button
            switch.addWidget(button)

        switch.addStretch(1)
        body.addLayout(switch)

        self._row_installed = KeyValueRow("Установлена версия")
        self._row_latest = KeyValueRow("Доступна версия")
        body.addWidget(self._row_installed)
        body.addWidget(self._row_latest)

        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE["sm"])

        self._check_button = QPushButton("Проверить обновления")
        self._check_button.clicked.connect(self._check_current)
        buttons.addWidget(self._check_button)

        self._install_button = QPushButton("Установить")
        self._install_button.setObjectName("Primary")
        self._install_button.setEnabled(False)
        self._install_button.clicked.connect(self._install_current)
        buttons.addWidget(self._install_button)
        buttons.addStretch(1)
        body.addLayout(buttons)

        self._progress = QProgressBar()
        self._progress.hide()
        body.addWidget(self._progress)

        self._status = QLabel("Нажмите «Проверить обновления»")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        body.addWidget(self._status)

        self._changelog = QTextBrowser()
        self._changelog.setPlaceholderText("Здесь появится описание релиза")
        self._changelog.setOpenExternalLinks(True)
        # Ссылки внутри описания Qt красит системным синим — тёмным, и на
        # тёмном фоне его просто не видно. Таблицей стилей приложения это не
        # лечится: текст здесь разбирается как HTML, и цвет ссылок берётся из
        # таблицы стилей самого документа.
        # Белым, а не цветом: палитра монохромная, цвет остаётся за
        # состояниями. Ссылку и так видно по подчёркиванию.
        self._changelog.document().setDefaultStyleSheet(
            f"a {{ color: {COLORS['text']}; }}"
            f"code {{ color: {COLORS['text_dim']}; }}"
        )
        body.addWidget(self._changelog, 1)

        # Откат есть только у ядра: его бэкапы мы храним сами, а прокси —
        # один файл, который просто перекачивается.
        self._rollback_row = QWidget()
        rollback = QHBoxLayout(self._rollback_row)
        rollback.setContentsMargins(0, 0, 0, 0)
        rollback.setSpacing(SPACE["sm"])

        self._backups = QComboBox()
        rollback.addWidget(self._backups, 1)

        self._rollback_button = QPushButton("Откатиться")
        self._rollback_button.clicked.connect(self._rollback)
        rollback.addWidget(self._rollback_button)
        body.addWidget(self._rollback_row)

        return card

    # --- переключение источника ------------------------------------------

    def _switch_source(self, source: str) -> None:
        """Показывает ядро или прокси в той же карточке."""
        self._source = source
        self._rollback_row.setVisible(source == CORE)
        self._changelog.setMarkdown("")
        self._status.setStyleSheet(f"color: {COLORS['text_muted']};")
        self._status.setText("Нажмите «Проверить обновления»")
        self._install_button.setEnabled(False)
        self._install_button.setText("Установить" if source == CORE else "Обновить")
        self.reload()

    def _check_current(self) -> None:
        self.check_updates() if self._source == CORE else self._check_proxy()

    def _install_current(self) -> None:
        self._install() if self._source == CORE else self._update_proxy()

    def _check_proxy(self) -> None:
        """Спрашивает GitHub о последнем релизе прокси."""
        if self._proxy_worker is not None and self._proxy_worker.isRunning():
            return

        self._check_button.setEnabled(False)
        self._status.setStyleSheet(f"color: {COLORS['text_muted']};")
        self._status.setText("Смотрю релизы прокси…")

        self._proxy_task = Task(telegram.latest_release)
        self._proxy_task.done.connect(self._show_proxy_release)
        self._proxy_task.failed.connect(self._proxy_failed)
        self._proxy_task.start()

    def _show_proxy_release(self, release) -> None:
        self._check_button.setEnabled(True)
        installed = telegram.installed_version()

        self._row_latest.set_value(f"{release.version} от {release.published_date}")
        self._changelog.setMarkdown(release.body or "Описание релиза отсутствует")

        # Прокси, поставленный до того, как версия стала запоминаться, тоже
        # можно обновить — просто мы не знаем, нужно ли это.
        outdated = not installed or github.is_newer(release.version, installed)
        self._install_button.setEnabled(telegram.is_installed() and outdated)

        if not telegram.is_installed():
            self._status.setText(
                "Прокси не установлен — поставить его можно на вкладке Telegram"
            )
        elif outdated:
            self._status.setStyleSheet(f"color: {COLORS['warning']};")
            self._status.setText(f"Доступно обновление до {release.version}")
        else:
            self._status.setStyleSheet(f"color: {COLORS['success']};")
            self._status.setText("Установлена последняя версия")

    def _build_extras_card(self) -> Card:
        card = Card("Списки и hosts")
        body = card.body()

        self._row_ipset = KeyValueRow("Режим IP-набора")
        body.addWidget(self._row_ipset)

        # Что это за список и есть ли он вообще — вопрос, который возникал у
        # каждого, кто видел кнопку «Обновить список IP-адресов».
        self._row_ipset_list = KeyValueRow("Скачанный список")
        body.addWidget(self._row_ipset_list)

        ipset_buttons = QHBoxLayout()
        ipset_buttons.setSpacing(SPACE["sm"])

        ipset_button = QPushButton("Обновить список IP-адресов")
        ipset_button.clicked.connect(self._update_ipset)
        ipset_buttons.addWidget(ipset_button)

        self._ipset_show = QPushButton("Показать файл")
        self._ipset_show.clicked.connect(self._show_ipset_file)
        ipset_buttons.addWidget(self._ipset_show)
        body.addLayout(ipset_buttons)

        note = QLabel(
            "Список собирает Flowseal. Он нужен режиму «по списку» из настроек: "
            "тогда обход применяется только к адресам из файла."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        # Без этого перенесённый текст не получает высоту под вторую строку
        # и уезжает под соседнюю строку карточки.
        note.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        body.addWidget(note)

        self._row_hosts = KeyValueRow("Секция в hosts")
        body.addWidget(self._row_hosts)

        hosts_apply = QPushButton("Записать hosts от Flowseal")
        hosts_apply.clicked.connect(self._apply_hosts)
        body.addWidget(hosts_apply)

        hosts_remove = QPushButton("Убрать нашу секцию из hosts")
        hosts_remove.clicked.connect(self._remove_hosts)
        body.addWidget(hosts_remove)

        hosts_note = QLabel(
            "Записи добавляются между маркерами, остальной файл не меняется, "
            "а перед каждой правкой сохраняется резервная копия."
        )
        hosts_note.setObjectName("Muted")
        hosts_note.setWordWrap(True)
        body.addWidget(hosts_note)

        body.addStretch(1)
        return card

    # --- действия -------------------------------------------------------

    def reload(self) -> None:
        self._row_app.set_value(
            f"{selfupdate.current_version()}"
            + ("" if selfupdate.is_frozen() else " (из исходников)")
        )

        if self._source == CORE:
            self._row_installed.set_value(coreinfo.describe().version_label)
        else:
            proxy_version = telegram.installed_version()
            self._row_installed.set_value(
                (proxy_version or "версия неизвестна")
                if telegram.is_installed()
                else "не установлен"
            )

        self._check_button.setEnabled(True)
        self._row_ipset.set_value(ipset.LABELS[ipset.status()])
        ipset_list = ipset.describe_list()
        self._row_ipset_list.set_value(ipset_list.label)
        self._ipset_show.setEnabled(ipset_list.present)

        state = hosts.status()
        self._row_hosts.set_value(
            f"{state.managed_lines} строк" if state.managed else "не записана"
        )

        self._backups.clear()
        backups = install.list_backups()
        for backup in backups:
            self._backups.addItem(backup.label, backup)
        self._backups.setEnabled(bool(backups))
        self._rollback_button.setEnabled(bool(backups))

    def show_known_updates(self, found: list) -> None:
        """Показывает то, что фоновая проверка уже нашла.

        Иначе выходит глупо: полоса вверху окна сообщает о новой версии,
        человек идёт по ней в этот раздел — а кнопка «Обновить» не горит, и
        надо нажать «Проверить», чтобы спросить GitHub о том же самом второй
        раз. Релиз у находки уже с собой, спрашивать нечего.
        """
        for available in found:
            if available.release is None:
                continue
            if available.what == updates.APP:
                self._app_checked(available.release)
            elif available.what == updates.CORE and self._source == CORE:
                self._show_release(available.release)

    def install_core(self) -> None:
        """Ставит ядро сразу, без лишних нажатий.

        Так приходят с дашборда: там главная кнопка при отсутствии ядра
        предлагает его поставить, и человеку нужен обход, а не экскурсия по
        разделам. Если о последнем релизе ещё не спрашивали, сперва спросим —
        установка начнётся, как только придёт ответ.
        """
        if self._latest is not None:
            self._install()
            return

        self._install_after_check = True
        self.check_updates()

    def check_updates(self) -> None:
        self._check_button.setEnabled(False)
        self._status.setText("Спрашиваю GitHub о последнем релизе…")

        self._task = Task(github.latest_release)
        self._task.done.connect(self._show_release)
        self._task.failed.connect(self._fail)
        self._task.start()

    def _show_release(self, release: github.Release) -> None:
        self._check_button.setEnabled(True)
        self._latest = release
        installed = coreinfo.read_version()

        self._row_latest.set_value(f"{release.version} от {release.published_date}")
        self._changelog.setMarkdown(release.body or "Описание релиза отсутствует")

        if github.is_newer(release.version, installed):
            self._install_button.setEnabled(True)
            self._status.setStyleSheet(f"color: {COLORS['warning']};")
            self._status.setText(f"Доступно обновление до {release.version}")
            if self._install_after_check:
                self._install_after_check = False
                self._install()
        else:
            self._install_after_check = False
            self._install_button.setEnabled(False)
            self._status.setStyleSheet(f"color: {COLORS['success']};")
            self._status.setText("Установлена последняя версия")

    def _install(self) -> None:
        if self._latest is None:
            return

        self.controller.stop()
        self._install_button.setEnabled(False)
        self._check_button.setEnabled(False)
        self._progress.setValue(0)
        self._progress.show()

        paths.ensure_dirs()
        self.busy_changed.emit(True)
        self._worker = CoreUpdateWorker(self._latest, paths.downloads_dir())
        self._worker.progress.connect(self._status.setText)
        self._worker.percent.connect(self._progress.setValue)
        self._worker.done.connect(self._installed)
        self._worker.failed.connect(self._fail)
        self._worker.start()

    def _installed(self, version: str) -> None:
        self.busy_changed.emit(False)
        self._progress.hide()
        self._check_button.setEnabled(True)
        self._status.setStyleSheet(f"color: {COLORS['success']};")
        self._status.setText(f"Установлена версия {version}")
        self.reload()
        self.controller.message.emit(f"Ядро обновлено до версии {version}")
        self.controller.refresh()
        self.something_updated.emit()

    def _rollback(self) -> None:
        backup = self._backups.currentData()
        if backup is None:
            return

        self.controller.stop()
        try:
            version = install.rollback(backup)
        except install.InstallError as error:
            self._fail(str(error))
            return

        self.reload()
        self.controller.message.emit(f"Выполнен откат на версию {version}")
        self.controller.refresh()

    def _update_ipset(self) -> None:
        self._status.setText("Скачиваю список IP-адресов…")
        self._task = Task(ipset.update_list)
        self._task.done.connect(self._ipset_updated)
        self._task.failed.connect(self._fail)
        self._task.start()

    def _update_proxy(self) -> None:
        """Ставит свежий tg-ws-proxy поверх установленного."""
        if self._proxy_worker is not None and self._proxy_worker.isRunning():
            return

        self._install_button.setEnabled(False)
        self._check_button.setEnabled(False)
        self._status.setStyleSheet(f"color: {COLORS['text_muted']};")
        self._status.setText("Спрашиваю GitHub о последнем релизе прокси…")
        self._progress.setValue(0)
        self._progress.show()

        self._proxy_worker = TelegramInstallWorker()
        self._proxy_worker.progress.connect(self._status.setText)
        self._proxy_worker.percent.connect(self._progress.setValue)
        self._proxy_worker.done.connect(self._proxy_updated)
        self._proxy_worker.failed.connect(self._proxy_failed)
        self._proxy_worker.start()

    def _proxy_updated(self, version: str) -> None:
        self._progress.hide()
        self._check_button.setEnabled(True)
        self._status.setStyleSheet(f"color: {COLORS['success']};")
        self._status.setText(f"Прокси обновлён до версии {version}")
        self.reload()

    def _proxy_failed(self, message: str) -> None:
        self._progress.hide()
        self._check_button.setEnabled(True)
        self._status.setStyleSheet(f"color: {COLORS['danger']};")
        self._status.setText(message)

    def _show_ipset_file(self) -> None:
        """Открывает папку со списком и подсвечивает сам файл."""
        info = ipset.describe_list()
        if info.file is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(info.file.parent)))

    def _ipset_updated(self, count: int) -> None:
        self._status.setStyleSheet(f"color: {COLORS['success']};")
        self._status.setText(f"Список IP-адресов обновлён, записей: {count}")
        self.reload()

    def _apply_hosts(self) -> None:
        self._status.setText("Скачиваю hosts…")
        self._task = Task(lambda: hosts.apply(hosts.fetch_upstream()))
        self._task.done.connect(self._hosts_applied)
        self._task.failed.connect(self._fail)
        self._task.start()

    def _hosts_applied(self, count: int) -> None:
        self._status.setStyleSheet(f"color: {COLORS['success']};")
        self._status.setText(f"В hosts записано строк: {count}")
        self.reload()

    def _remove_hosts(self) -> None:
        if hosts.remove():
            self.controller.message.emit("Секция убрана из hosts")
        else:
            self.controller.message.emit("В hosts нет нашей секции")
        self.reload()

    def _fail(self, message: str) -> None:
        self.busy_changed.emit(False)
        self._progress.hide()
        self._check_button.setEnabled(True)
        self._status.setStyleSheet(f"color: {COLORS['danger']};")
        self._status.setText(message)
