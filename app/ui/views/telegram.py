"""Экран Telegram.

Telegram Desktop не ходит по TLS с SNI, поэтому обычные стратегии zapret на
него не действуют. Чинится отдельным локальным MTProto-прокси — он ставится
и управляется отсюда.
"""

from __future__ import annotations

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import telegram
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, KeyValueRow, StatusPill, view_header
from app.ui.workers import Task, TelegramInstallWorker


class TelegramView(QWidget):
    """Установка, запуск и настройка прокси для Telegram."""

    # Долгая работа: боковое меню рисует кружок, а трей сообщает о
    # завершении, если окно успели свернуть.
    busy_changed = pyqtSignal(bool)

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

        columns = QHBoxLayout()
        columns.setSpacing(SPACE["lg"])
        columns.addWidget(self._build_proxy_card(), 1)
        columns.addWidget(self._build_connect_card(), 1)
        layout.addLayout(columns)
        layout.addStretch(1)

    def _build_proxy_card(self) -> Card:
        card = Card("Прокси")
        body = card.body()

        self._pill = StatusPill("состояние неизвестно", COLORS["text_muted"])
        body.addWidget(self._pill)

        self._row_state = KeyValueRow("Состояние")
        self._row_port = KeyValueRow("Адрес")
        body.addWidget(self._row_state)
        body.addWidget(self._row_port)

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

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.hide()
        body.addWidget(self._progress)

        # Главное, чего не хватало: видно, дошло ли дело до самого Telegram.
        self._connection = QLabel("")
        self._connection.setWordWrap(True)
        self._connection.setVisible(False)
        body.addWidget(self._connection)

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
