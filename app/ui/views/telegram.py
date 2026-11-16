"""Экран Telegram.

Telegram Desktop не ходит по TLS с SNI, поэтому обычные стратегии zapret на
него не действуют. Чинится отдельным локальным MTProto-прокси — он ставится
и управляется отсюда.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core import telegram
from app.ui import dialogs
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import (
    Card,
    Divider,
    KeyValueRow,
    ShineProgressBar,
    StatusPill,
    TabStrip,
    view_header,
)
from app.ui.workers import Task, TelegramInstallWorker


class TelegramView(QWidget):
    """Установка, запуск и настройка прокси для Telegram."""

    # Долгая работа: боковое меню рисует кружок, а трей сообщает о
    # завершении, если окно успели свернуть.
    busy_changed = pyqtSignal(bool)
    # Прокси поставлен или обновлён: напоминание о его обновлении пора снять.
    something_updated = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._task: Task | None = None
        self._worker: TelegramInstallWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Telegram",
                "Стратегии zapret Telegram Desktop не чинят: он не использует TLS с SNI, "
                "и обходу не за что зацепиться. Помогает локальный MTProto-прокси "
                "tg-ws-proxy от авторов самой сборки.",
            )
        )

        # Вкладки, как в настройках программы: настроек у прокси много, а на главной
        # вкладке нужно одно — работает ли он и подключён ли Telegram.
        self._tabs = TabStrip([("proxy", "Прокси"), ("settings", "Настройки")])
        layout.addWidget(self._tabs)

        main = QWidget()
        columns = QHBoxLayout(main)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(SPACE["lg"])
        columns.addWidget(self._build_proxy_card(), 1)
        columns.addWidget(self._build_connect_card(), 1)

        self._pages = QStackedWidget()
        self._pages.addWidget(main)
        self._pages.addWidget(self._build_settings_page())
        layout.addWidget(self._pages, 1)
        self._tabs.changed.connect(self._switch_tab)

    def _build_proxy_card(self) -> Card:
        card = Card("Прокси")
        body = card.body()

        self._pill = StatusPill("состояние неизвестно", COLORS["text_muted"])
        body.addWidget(self._pill)

        self._row_state = KeyValueRow("Состояние")
        self._row_port = KeyValueRow("Адрес")
        body.addWidget(self._row_state)
        body.addWidget(self._row_port)
        KeyValueRow.line_up(self._row_state, self._row_port)

        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE["sm"])

        self._install_button = QPushButton("Установить")
        self._install_button.clicked.connect(self._install)
        buttons.addWidget(self._install_button)

        self._toggle_button = QPushButton("Запустить")
        self._toggle_button.setObjectName("Primary")
        self._toggle_button.clicked.connect(self._toggle)
        buttons.addWidget(self._toggle_button)
        buttons.addStretch(1)
        body.addLayout(buttons)

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        body.addWidget(self._status)

        self._progress = ShineProgressBar()
        self._progress.setRange(0, 100)
        self._progress.hide()
        body.addWidget(self._progress)

        # Главное, чего не хватало: видно, дошло ли дело до самого Telegram.
        self._connection = QLabel("")
        self._connection.setWordWrap(True)
        self._connection.setVisible(False)
        body.addWidget(self._connection)

        # Прокси запущен, Telegram стучится, а до серверов не доходит ничего. Так было
        # у человека, которому помогла галочка «Без TLS»: провайдер резал защищённые
        # соединения к Cloudflare, а сам он видел только «Telegram не грузится».
        self._stuck = QLabel("")
        self._stuck.setWordWrap(True)
        self._stuck.setStyleSheet(f"color: {COLORS['warning']};")
        self._stuck.hide()
        body.addWidget(self._stuck)

        self._insecure_button = QPushButton("Включить «Без TLS» и перезапустить")
        self._insecure_button.clicked.connect(self._enable_insecure)
        self._insecure_button.hide()
        body.addWidget(self._insecure_button)

        body.addStretch(1)
        return card

    def _build_connect_card(self) -> Card:
        card = Card("Подключение")
        body = card.body()

        hint = QLabel(
            "Нажмите «Открыть в Telegram» — приложение само пропишет прокси в настройках. "
            "Если Telegram не отзовётся, скопируйте ссылку и откройте её из «Избранного»."
        )
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        body.addWidget(hint)

        self._open_button = QPushButton("Открыть в Telegram")
        self._open_button.clicked.connect(self._open_link)
        body.addWidget(self._open_button)

        self._copy_button = QPushButton("Скопировать ссылку")
        self._copy_button.clicked.connect(self._copy_link)
        body.addWidget(self._copy_button)

        manual = QLabel(
            "Вручную: Настройки → Продвинутые настройки → Тип соединения → "
            "Использовать прокси → MTProto."
        )
        manual.setObjectName("Muted")
        manual.setWordWrap(True)
        body.addWidget(manual)

        self._row_secret = KeyValueRow("Секрет")
        body.addWidget(self._row_secret)

        web_note = QLabel(
            "Telegram Web прокси не нужен — он работает по обычному TLS, и его "
            "чинит сам обход, если домены есть в списках."
        )
        web_note.setObjectName("Muted")
        web_note.setWordWrap(True)
        body.addWidget(web_note)

        body.addStretch(1)
        return card

    # --- настройки прокси ----------------------------------------------

    def _build_settings_page(self) -> QScrollArea:
        """Настройки tg-ws-proxy — те, что имеют смысл, когда прокси ведёт программа.

        Язык, тема и автозапуск окна прокси не показываем: окна мы не открываем, а
        автозапуском и обновлениями управляет программа.
        """
        card = Card()
        body = card.body()

        def section(title: str) -> None:
            label = QLabel(title)
            label.setObjectName("ViewTitle")
            label.setStyleSheet("font-size: 14px;")
            body.addWidget(label)

        def hint(text: str) -> None:
            label = QLabel(text)
            label.setObjectName("Muted")
            label.setWordWrap(True)
            body.addWidget(label)

        def number(title: str, key: str) -> QSpinBox:
            row = QHBoxLayout()
            row.setSpacing(SPACE["sm"])
            row.addWidget(QLabel(title))
            spin = QSpinBox()
            spin.setRange(*telegram.LIMITS[key])
            row.addWidget(spin)
            row.addStretch(1)
            body.addLayout(row)
            return spin

        section("Подключение")
        self._port = number("Порт", "port")
        key_row = QHBoxLayout()
        key_row.setSpacing(SPACE["sm"])
        new_key = QPushButton("Новый ключ")
        new_key.setToolTip(
            "Ключ — пароль к прокси. Сменить стоит, если ссылка на прокси попала к кому-то ещё"
        )
        new_key.clicked.connect(self._new_key)
        key_row.addWidget(new_key)
        key_row.addStretch(1)
        body.addLayout(key_row)
        hint("После смены порта или ключа нажмите «Открыть в Telegram» ещё раз.")

        body.addWidget(Divider())
        section("Cloudflare")
        self._cfproxy = QCheckBox("Запасной путь через Cloudflare")
        self._cfproxy.setToolTip(
            "Если серверы Telegram напрямую недоступны, трафик идёт через Cloudflare"
        )
        body.addWidget(self._cfproxy)
        self._h2 = QCheckBox("Медиа через HTTP/2")
        self._h2.setToolTip("Фото и видео идут через одно соединение — быстрее, если его не режут")
        body.addWidget(self._h2)
        self._no_secure = QCheckBox("Без TLS — к Cloudflare по порту 80")
        body.addWidget(self._no_secure)
        hint(
            "Помогает, если провайдер режет защищённые соединения к Cloudflare: Telegram "
            "стучится в прокси, а дальше не идёт ничего."
        )

        self._own_domain = QCheckBox("Свой домен Cloudflare")
        self._own_domains = QLineEdit()
        self._own_domains.setPlaceholderText("example.com")
        self._worker = QCheckBox("Cloudflare Worker")
        self._worker_domains = QLineEdit()
        self._worker_domains.setPlaceholderText("домены через запятую")
        pairs = ((self._own_domain, self._own_domains), (self._worker, self._worker_domains))
        for box, line in pairs:
            row = QHBoxLayout()
            row.setSpacing(SPACE["sm"])
            row.addWidget(box)
            row.addWidget(line, 1)
            body.addLayout(row)
            box.toggled.connect(line.setEnabled)

        body.addWidget(Divider())
        section("Датацентры Telegram")
        hint("По одному правилу на строку: номер:IP.")
        self._dc = QPlainTextEdit()
        self._dc.setFixedHeight(80)
        body.addWidget(self._dc)

        body.addWidget(Divider())
        section("Журнал и производительность")
        self._verbose = QCheckBox("Подробный журнал")
        body.addWidget(self._verbose)
        self._buf = number("Буфер, КБ", "buf_kb")
        self._pool = number("Пул соединений", "pool_size")
        self._log_size = number("Размер журнала, МБ", "log_max_mb")

        body.addWidget(Divider())
        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE["sm"])
        save = QPushButton("Сохранить")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_settings)
        buttons.addWidget(save)
        defaults = QPushButton("Как по умолчанию")
        defaults.setToolTip(
            "Вернёт значения tg-ws-proxy по умолчанию. Сохранится — после «Сохранить»"
        )
        defaults.clicked.connect(lambda: self._fill_settings(dict(telegram.SETTINGS)))
        buttons.addWidget(defaults)
        buttons.addStretch(1)
        body.addLayout(buttons)

        self._settings_status = QLabel("")
        self._settings_status.setObjectName("Muted")
        self._settings_status.setWordWrap(True)
        body.addWidget(self._settings_status)
        body.addStretch(1)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(card, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _switch_tab(self, key: str) -> None:
        self._pages.setCurrentIndex(0 if key == "proxy" else 1)
        if key == "settings":
            self._fill_settings(telegram.settings())

    def _fill_settings(self, values: dict) -> None:
        self._port.setValue(int(values.get("port", self._port.value())))
        self._cfproxy.setChecked(bool(values["cfproxy"]))
        self._h2.setChecked(bool(values["h2"]))
        self._no_secure.setChecked(bool(values["no_secure"]))
        self._own_domain.setChecked(bool(values["cfproxy_user_domain_enabled"]))
        self._own_domains.setText(", ".join(values["cfproxy_user_domain"]))
        self._own_domains.setEnabled(self._own_domain.isChecked())
        self._worker.setChecked(bool(values["cfproxy_worker_enabled"]))
        self._worker_domains.setText(", ".join(values["cfproxy_worker_domain"]))
        self._worker_domains.setEnabled(self._worker.isChecked())
        self._dc.setPlainText("\n".join(values["dc_ip"]))
        self._verbose.setChecked(bool(values["verbose"]))
        self._buf.setValue(int(values["buf_kb"]))
        self._pool.setValue(int(values["pool_size"]))
        self._log_size.setValue(int(values["log_max_mb"]))
        self._settings_status.setText("")

    def _say_settings(self, text: str, colour: str) -> None:
        self._settings_status.setStyleSheet(f"color: {colour};")
        self._settings_status.setText(text)

    def _save_settings(self) -> None:
        try:
            values = {
                "port": self._port.value(),
                "cfproxy": self._cfproxy.isChecked(),
                "h2": self._h2.isChecked(),
                "no_secure": self._no_secure.isChecked(),
                "cfproxy_user_domain_enabled": self._own_domain.isChecked(),
                "cfproxy_user_domain": telegram.parse_domains(self._own_domains.text()),
                "cfproxy_worker_enabled": self._worker.isChecked(),
                "cfproxy_worker_domain": telegram.parse_domains(self._worker_domains.text()),
                "dc_ip": telegram.parse_dc_rules(self._dc.toPlainText()),
                "verbose": self._verbose.isChecked(),
                "buf_kb": self._buf.value(),
                "pool_size": self._pool.value(),
                "log_max_mb": self._log_size.value(),
            }
            if values["cfproxy_user_domain_enabled"] and not values["cfproxy_user_domain"]:
                raise ValueError("включён свой домен, а самого домена нет")
            if values["cfproxy_worker_enabled"] and not values["cfproxy_worker_domain"]:
                raise ValueError("включён Worker, а доменов для него нет")
            telegram.save_settings(values)
        except ValueError as error:
            self._say_settings(f"Не сохранено: {error}", COLORS["danger"])
            return

        self._apply_to_running("Сохранено")

    def _apply_to_running(self, done: str) -> None:
        """Прокси читает настройки только при старте — работающий перезапускаем."""
        proxy = self.controller.telegram
        if proxy.is_running():
            try:
                proxy.restart()
            except telegram.TelegramError as error:
                self._say_settings(
                    f"{done}, но прокси не перезапустился: {error}", COLORS["danger"]
                )
                return
            self._say_settings(f"{done}, прокси перезапущен", COLORS["success"])
        else:
            self._say_settings(f"{done}. Подействует, когда прокси запустится", COLORS["success"])
        self.controller.refresh()
        self.reload()

    def _new_key(self) -> None:
        if not dialogs.confirm(
            self,
            "Новый ключ",
            "Сменить ключ прокси?",
            "Telegram со старым ключом к прокси больше не подключится — после смены нажмите "
            "«Открыть в Telegram», чтобы прописать новый.",
            action="Сменить ключ",
        ):
            return
        telegram.new_secret()
        self._apply_to_running("Ключ сменён")

    def _enable_insecure(self) -> None:
        telegram.save_settings({"no_secure": True})
        self._insecure_button.hide()
        self._stuck.setText("Включено «Без TLS», прокси перезапущен. Проверьте Telegram.")
        self._apply_to_running("Включено «Без TLS»")

    # --- состояние ------------------------------------------------------

    def reload(self) -> None:
        state = self.controller.telegram.state()

        self._pill.set_state(
            f"прокси: {state.label}",
            COLORS["success"] if state.running else COLORS["text_muted"],
        )
        self._row_state.set_value(state.label)
        self._row_port.set_value(f"{state.host}:{state.port}" if state.installed else "—")
        self._row_secret.set_value(state.secret or "—")

        self._install_button.setText("Переустановить" if state.installed else "Установить")
        self._toggle_button.setText("Остановить" if state.running else "Запустить")
        self._toggle_button.setEnabled(state.installed)

        has_link = bool(state.link)
        self._open_button.setEnabled(has_link and state.running)
        self._copy_button.setEnabled(has_link)

        if not state.installed:
            self._status.setText(
                "Прокси ещё не скачан. Он берётся из официальных релизов Flowseal "
                "и кладётся в папку приложения, не трогая вашу установку, если она есть."
            )

        self._show_connection(state.running, self.controller.status.telegram_connected)

    def on_status(self, status) -> None:
        """Обновляет надпись о подключении, когда опрос принёс новое состояние.

        Раньше надпись считалась один раз — при открытии вкладки. Человек
        открывал её, видел «Telegram ещё не подключился», нажимал «Открыть в
        Telegram», клиент подключался, а надпись так и оставалась жёлтой, пока
        не уйдёшь со вкладки и не вернёшься. Опрос состояния и так идёт в фоне
        каждые несколько секунд и уже знает ответ.
        """
        self._show_connection(status.telegram_running, status.telegram_connected)
        self._show_stuck(status.telegram_running and status.telegram_stuck)

    def _show_stuck(self, stuck: bool) -> None:
        """Telegram стучится, а дальше не идёт ничего — говорим, что попробовать."""
        self._stuck.setVisible(stuck)
        if not stuck:
            self._insecure_button.hide()
            return
        # Раз Telegram стучится в прокси, «ещё не подключился» рядом было бы неправдой.
        self._connection.hide()

        current = telegram.settings()
        offer = current["cfproxy"] and not current["no_secure"]
        self._stuck.setText(
            "Telegram подключается к прокси, но до серверов не доходит ничего — ни напрямую, "
            "ни через Cloudflare. "
            + (
                "Похоже, провайдер режет защищённые соединения к Cloudflare."
                if offer
                else "Попробуйте свой домен Cloudflare или Worker во вкладке «Настройки»."
            )
        )
        self._insecure_button.setVisible(offer)

    def _show_connection(self, running: bool, connected: bool) -> None:
        """Говорит, дошло ли дело до самого Telegram.

        Запущенный прокси сам по себе ничего не чинит: пока человек не
        добавит его в настройки Telegram, трафик идёт мимо. Прямо спросить
        клиент нельзя, зато видно установленное соединение с нашим портом.

        Ответ берётся готовым из опроса, а не спрашивается здесь: список
        соединений читается долго, и в потоке интерфейса ему не место.
        """
        if not running:
            self._connection.setVisible(False)
            return

        self._connection.setVisible(True)
        if connected:
            self._connection.setText("Telegram подключён к прокси — всё на месте")
            self._connection.setStyleSheet(f"color: {COLORS['success']};")
            return

        self._connection.setText(
            "Прокси запущен, но Telegram к нему ещё не подключился. "
            "Нажмите «Открыть в Telegram» — клиент пропишет прокси сам."
        )
        self._connection.setStyleSheet(f"color: {COLORS['warning']};")

    def install_proxy(self) -> None:
        """Ставит прокси сразу: согласие спросили на главном экране.

        Там жмут кнопку «включить», и человеку нужен работающий Telegram, а
        не экскурсия по разделам. Сюда он попадает только затем, чтобы
        видеть загрузку — файл весит два десятка мегабайт.
        """
        if not self._install_button.isEnabled():
            return
        self._install()

    def _install(self) -> None:
        self._install_button.setEnabled(False)
        self._status.setStyleSheet(f"color: {COLORS['text_muted']};")
        self._status.setText("Спрашиваю GitHub о последнем релизе tg-ws-proxy…")
        self._progress.setValue(0)
        self._progress.show()

        self.busy_changed.emit(True)
        self._worker = TelegramInstallWorker()
        self._worker.progress.connect(self._status.setText)
        self._worker.percent.connect(self._progress.setValue)
        self._worker.done.connect(self._installed)
        self._worker.failed.connect(self._fail)
        self._worker.start()

    def _installed(self, version: str) -> None:
        self.busy_changed.emit(False)
        self._progress.hide()
        self._install_button.setEnabled(True)
        self._status.setStyleSheet(f"color: {COLORS['success']};")
        self._status.setText(f"Установлена версия {version}")
        self.reload()
        self.something_updated.emit()

    def _toggle(self) -> None:
        proxy = self.controller.telegram
        try:
            if proxy.is_running():
                proxy.stop()
                self._status.setText("Прокси остановлен")
            else:
                if not telegram.port_is_free():
                    self._status.setStyleSheet(f"color: {COLORS['warning']};")
                    self._status.setText(
                        f"Порт {telegram.DEFAULT_PORT} уже занят — возможно, прокси "
                        "запущен отдельно. Закройте его и попробуйте снова."
                    )
                    return
                state = proxy.start()
                self._status.setStyleSheet(f"color: {COLORS['success']};")
                self._status.setText(f"Прокси слушает {state.host}:{state.port}")
        except telegram.TelegramError as error:
            self._fail(str(error))
            return

        self.reload()

    def _open_link(self) -> None:
        link = self.controller.telegram.state().link
        if link:
            QDesktopServices.openUrl(QUrl(link))

    def _copy_link(self) -> None:
        link = self.controller.telegram.state().link
        if not link:
            return
        QApplication.clipboard().setText(link)
        self.controller.message.emit("Ссылка скопирована — откройте её в Telegram")

    def _fail(self, message: str) -> None:
        self.busy_changed.emit(False)
        self._progress.hide()
        self._install_button.setEnabled(True)
        self._status.setStyleSheet(f"color: {COLORS['danger']};")
        self._status.setText(message)
