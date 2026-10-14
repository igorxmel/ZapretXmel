"""Экран пользовательских списков доменов и адресов."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import lists
from app.core.lists import USER_LISTS, UserList
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, view_header


class ListsView(QWidget):
    """Редактор файлов `*-user.txt`.

    Правим только пользовательские файлы: штатные списки перезаписываются при
    каждом обновлении ядра, и правки в них всё равно потерялись бы.
    """

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._current: UserList = USER_LISTS[0]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["lg"])
        layout.addWidget(
            view_header(
                "Списки",
                "Свои домены и адреса. Эти файлы переживают обновление ядра, "
                "в отличие от штатных списков сборки.",
            )
        )

        card = Card()
        body = card.body()

        selector = QHBoxLayout()
        selector.setSpacing(SPACE["md"])

        self._selector = QComboBox()
        self._selector.addItems([user_list.title for user_list in USER_LISTS])
        self._selector.currentIndexChanged.connect(self._switch_list)
        selector.addWidget(self._selector, 1)

        import_button = QPushButton("Импорт из другой папки zapret")
        import_button.clicked.connect(self._import)
        selector.addWidget(import_button)

        body.addLayout(selector)

        self._hint = QLabel(self._current.hint)
        self._hint.setObjectName("Dim")
        self._hint.setWordWrap(True)
        body.addWidget(self._hint)

        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText("По одной записи на строку")
        body.addWidget(self._editor, 1)

        footer = QHBoxLayout()
        footer.setSpacing(SPACE["md"])

        save_button = QPushButton("Сохранить")
        save_button.setObjectName("Primary")
        save_button.clicked.connect(self._save)
        footer.addWidget(save_button)

        reload_button = QPushButton("Отменить правки")
        reload_button.clicked.connect(self.reload)
        footer.addWidget(reload_button)

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        footer.addWidget(self._status, 1)
        body.addLayout(footer)

        layout.addWidget(card, 1)

    def reload(self) -> None:
        """Перечитывает текущий список с диска."""
        lists.ensure_user_lists()
        content = lists.read(self._current)

        self._editor.setPlainText("\n".join(content.entries))
        self._hint.setText(self._current.hint)
        self._status.setStyleSheet(f"color: {COLORS['text_muted']};")

        if content.invalid:
            self._status.setText(
                f"В файле есть нечитаемые строки ({len(content.invalid)}) — "
                "при сохранении они будут удалены"
            )
        else:
            self._status.setText(f"Записей: {len(content.entries)}")

    def _switch_list(self, index: int) -> None:
        if 0 <= index < len(USER_LISTS):
            self._current = USER_LISTS[index]
            self.reload()

    def _save(self) -> None:
        raw = [line.strip() for line in self._editor.toPlainText().splitlines()]
        entries = [line for line in raw if line and not line.startswith("#")]

        rejected = [line for line in entries if not lists.validate(line, self._current.kind)]
        saved = lists.write(self._current, entries, lists.read(self._current).comments)

        if rejected:
            self._status.setStyleSheet(f"color: {COLORS['warning']};")
            self._status.setText(
                f"Сохранено записей: {saved}. Отброшено как некорректные: {', '.join(rejected[:3])}"
                + (" и другие" if len(rejected) > 3 else "")
            )
        else:
            self._status.setStyleSheet(f"color: {COLORS['success']};")
            self._status.setText(f"Сохранено записей: {saved}")

        self.controller.message.emit(
            "Списки сохранены. Чтобы изменения вступили в силу, перезапустите обход."
        )

    def _import(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Выберите папку с другой установкой zapret"
        )
        if not directory:
            return

        imported = lists.import_from(Path(directory))
        if not imported:
            self.controller.message.emit("В указанной папке не нашлось пользовательских списков")
            return

        total = sum(imported.values())
        self.reload()
        self.controller.message.emit(f"Добавлено записей: {total}")
