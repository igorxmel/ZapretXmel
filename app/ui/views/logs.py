"""Экран логов: вывод winws и журнал самого приложения."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import paths
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, view_header

MAX_LINES = 2000

WINWS = "winws"
APP = "app"


class LogsView(QWidget):
    """Живой вывод winws — первое место, куда стоит смотреть, если обход падает."""

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._source = WINWS
        # Строки держим отдельно от показанного текста: поиск прячет часть,
        # а терять её нельзя — иначе снятый фильтр покажет пустоту.
        self._lines: dict[str, list[str]] = {WINWS: [], APP: []}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Логи",
                "Вывод winws виден только в режиме обычного процесса: запущенная "
                "как служба программа пишет в системный журнал, а не нам.",
            )
        )

        card = Card()
        body = card.body()

        head = QHBoxLayout()
        head.setSpacing(SPACE["sm"])

        self._tabs = QButtonGroup(self)
        self._tabs.setExclusive(True)
        self._tab_buttons: dict[str, QPushButton] = {}
        for key, title in ((WINWS, "Вывод winws"), (APP, "Журнал программы")):
            button = QPushButton(title)
            button.setObjectName("Chip")
            button.setCheckable(True)
            button.setChecked(key == WINWS)
            button.clicked.connect(lambda _, source=key: self._switch(source))
            self._tabs.addButton(button)
            self._tab_buttons[key] = button
            head.addWidget(button)

        head.addStretch(1)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск по строкам")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(260)
        self._search.textChanged.connect(self._redraw)
        head.addWidget(self._search)
        body.addLayout(head)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(MAX_LINES)
        body.addWidget(self._view, 1)

        self._count = QLabel("")
        self._count.setObjectName("Muted")
        body.addWidget(self._count)

        footer = QHBoxLayout()
        footer.setSpacing(SPACE["md"])

        clear_button = QPushButton("Очистить")
        clear_button.clicked.connect(self._clear)
        footer.addWidget(clear_button)

        copy_button = QPushButton("Скопировать")
        copy_button.setToolTip("Кладёт показанные строки в буфер обмена")
        copy_button.clicked.connect(self._copy)
        footer.addWidget(copy_button)

        folder_button = QPushButton("Открыть папку с логами")
        folder_button.clicked.connect(self._open_folder)
        footer.addWidget(folder_button)
        footer.addStretch(1)
        body.addLayout(footer)

        layout.addWidget(card, 1)

        controller.log_line.connect(self.append)

    # --- данные ---------------------------------------------------------

    def append(self, line: str) -> None:
        self._lines[WINWS].append(line)
        del self._lines[WINWS][:-MAX_LINES]

        if self._source != WINWS:
            return
        if self._matches(line):
            self._view.appendPlainText(line)
            self._update_count()

    def load_tail(self, lines: list[str]) -> None:
        """Подхватывает уже накопленный вывод при первом открытии экрана."""
        if lines and not self._lines[WINWS]:
            self._lines[WINWS] = list(lines)
            self._redraw()

    def reload(self) -> None:
        """Журнал перечитывается при каждом открытии экрана: он растёт сам."""
        if self._source == APP:
            self._read_app_log()
        self._redraw()

    def _read_app_log(self) -> None:
        path = paths.logs_dir() / "app.log"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self._lines[APP] = ["Журнал пока пуст."]
            return

        self._lines[APP] = text.splitlines()[-MAX_LINES:]

    # --- показ ----------------------------------------------------------

    def _switch(self, source: str) -> None:
        self._source = source
        if source == APP:
            self._read_app_log()
        self._redraw()

    def _matches(self, line: str) -> bool:
        needle = self._search.text().strip().lower()
        return not needle or needle in line.lower()

    def _visible(self) -> list[str]:
        return [line for line in self._lines[self._source] if self._matches(line)]

    def _redraw(self) -> None:
        self._view.setPlainText("\n".join(self._visible()))
        self._view.verticalScrollBar().setValue(self._view.verticalScrollBar().maximum())
        self._update_count()

    def _update_count(self) -> None:
        total = len(self._lines[self._source])
        shown = len(self._visible())

        if not self._search.text().strip():
            self._count.setText(f"Строк: {total}")
            self._count.setStyleSheet(f"color: {COLORS['text_muted']};")
            return

        self._count.setText(f"Найдено {shown} из {total}")
        self._count.setStyleSheet(
            f"color: {COLORS['text_muted'] if shown else COLORS['warning']};"
        )

    # --- действия -------------------------------------------------------

    def _clear(self) -> None:
        """Чистит только показанное.

        Файл журнала не трогаем: он нужен, когда что-то сломалось, а чистят
        экран обычно чтобы посмотреть на свежий вывод.
        """
        self._lines[self._source].clear()
        self._redraw()

    def _copy(self) -> None:
        QApplication.clipboard().setText("\n".join(self._visible()))
        self.controller.message.emit("Показанные строки скопированы")

    def _open_folder(self) -> None:
        paths.ensure_dirs()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.logs_dir())))
