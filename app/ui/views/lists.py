"""Экран пользовательских списков доменов и адресов."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import community, lists
from app.core.lists import USER_LISTS, UserList
from app.ui import dialogs
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, view_header
from app.ui.workers import Task

ADD_FROM_CATALOG = "Добавить к моим"


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
                "Свои домены вдобавок к тем, что уже знает сборка. Нужны, "
                "когда обход работает, но какой-то один сайт всё равно не "
                "открывается — впишите его здесь. Эти файлы переживают "
                "обновление ядра, в отличие от штатных списков сборки.",
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
        # Кнопка для тех, кто переезжает с консольной сборки: она ищет
        # такие же файлы в чужой папке. Если вы ничего туда не дописывали
        # или другой установки нет — находить нечего, и это не поломка.
        import_button.setToolTip(
            "Переносит свои домены из другой установки zapret. Ищет в ней "
            "такие же файлы *-user.txt — если вы их там не заполняли, "
            "переносить будет нечего."
        )
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

        # Обмен списками файлами: так ими делятся в чатах. Импорт добавляет к своим, а
        # не заменяет их, и попадает сначала в редактор — сохраняет человек сам.
        load_button = QPushButton("Добавить из файла…")
        load_button.setToolTip(
            "Записи из файла .txt добавятся к уже имеющимся. Ссылки сводятся к доменам, "
            "комментарии и повторы пропускаются. Посмотрите и нажмите «Сохранить»"
        )
        load_button.clicked.connect(self._load_file)
        footer.addWidget(load_button)

        export_button = QPushButton("Сохранить в файл…")
        export_button.setToolTip("Записывает текущий список в файл .txt, например чтобы поделиться")
        export_button.clicked.connect(self._export_file)
        footer.addWidget(export_button)

        # Готовые списки от других — из ветки community-lists этого репозитория.
        self._community_button = QPushButton("Каталог сообщества…")
        self._community_button.setToolTip(
            "Готовые списки доменов, которые прислали другие пользователи и проверил автор. "
            "Выбранный добавится к вашим записям в редакторе — сохраняете вы сами"
        )
        self._community_button.clicked.connect(self._open_catalog)
        footer.addWidget(self._community_button)

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

    def _editor_entries(self) -> list[str]:
        raw = [line.strip() for line in self._editor.toPlainText().splitlines()]
        return [line for line in raw if line and not line.startswith("#")]

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Добавить записи из файла", "", "Текстовые файлы (*.txt);;Все файлы (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        except OSError as error:
            self.controller.error.emit(f"Файл не прочитан: {error}")
            return

        good, bad = lists.parse_import(text, self._current.kind)
        self._merge(good, bad)

    def _merge(self, good: list[str], bad: list[str]) -> None:
        """Добавляет записи к тем, что в редакторе, и говорит, сколько вышло."""
        current = self._editor_entries()
        known = {entry.lower() for entry in current}
        fresh = [entry for entry in good if entry.lower() not in known]
        if fresh:
            self._editor.setPlainText("\n".join([*current, *fresh]))

        tone = COLORS["warning"] if bad or not fresh else COLORS["success"]
        self._status.setStyleSheet(f"color: {tone};")
        text = (
            f"Добавлено записей: {len(fresh)} — проверьте и нажмите «Сохранить»."
            if fresh else "Новых записей в файле нет."
        )
        if bad:
            text += f" Не подошло: {', '.join(bad[:3])}" + (" и другие" if len(bad) > 3 else "")
        self._status.setText(text)

    def _export_file(self) -> None:
        suggested = self._current.filename
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить список в файл", suggested, "Текстовые файлы (*.txt)"
        )
        if not path:
            return
        entries = [e for e in self._editor_entries() if lists.validate(e, self._current.kind)]
        text = lists.export_text(entries, self._current.kind)
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as error:
            self.controller.error.emit(f"Файл не записан: {error}")
            return
        self._status.setStyleSheet(f"color: {COLORS['success']};")
        self._status.setText(f"Записей в файле: {len(text.split())}")

    # --- каталог сообщества ----------------------------------------------

    def _open_catalog(self) -> None:
        self._community_button.setEnabled(False)
        self._status.setStyleSheet(f"color: {COLORS['text_muted']};")
        self._status.setText("Загружаю каталог сообщества…")
        self._catalog_task = Task(community.catalog)
        self._catalog_task.done.connect(self._show_catalog)
        self._catalog_task.failed.connect(self._catalog_failed)
        self._catalog_task.start()

    def _catalog_failed(self, message: str) -> None:
        self._community_button.setEnabled(True)
        self._status.setStyleSheet(f"color: {COLORS['warning']};")
        self._status.setText(f"Каталог не загрузился: {message}")

    def _show_catalog(self, entries: list[community.Entry]) -> None:
        self._community_button.setEnabled(True)
        self._status.setText("")
        dialog = dialogs.Dialog(
            self,
            "Каталог сообщества",
            "Готовые списки от других пользователей",
            "Выбранный список добавится к вашим записям в редакторе — посмотрите и нажмите "
            "«Сохранить». Прислать свой можно pull request'ом в ветку community-lists.",
        )
        if not entries:
            empty = QLabel(
                f'В каталоге пока нет списков. <a href="{community.BROWSE_URL}">Как добавить '
                "свой</a> — первый попадёт сюда."
            )
            empty.setOpenExternalLinks(True)
            empty.setWordWrap(True)
            dialog.insert_widget(empty)
            dialog.add_action("Понятно", primary=True)
            dialog.ask()
            return

        picker = QListWidget()
        picker.setObjectName("CatalogList")
        for entry in entries:
            item = QListWidgetItem(f"{entry.title}  ·  {entry.kind_label}  ·  {entry.author}")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            picker.addItem(item)
        picker.setMinimumHeight(220)
        about = QLabel("")
        about.setObjectName("Dim")
        about.setWordWrap(True)
        by_id = {entry.id: entry for entry in entries}

        def describe_choice() -> None:
            chosen = picker.currentItem()
            entry = by_id.get(chosen.data(Qt.ItemDataRole.UserRole)) if chosen else None
            about.setText(
                f"{entry.description}\nПопадёт в «{entry.target.title}»." if entry else ""
            )

        picker.currentItemChanged.connect(lambda *_: describe_choice())
        picker.setCurrentRow(0)
        dialog.insert_widget(picker)
        dialog.insert_widget(about)
        dialog.setFixedWidth(640)
        dialog.add_action("Отмена")
        dialog.add_action(ADD_FROM_CATALOG, primary=True)
        if dialog.ask() != ADD_FROM_CATALOG or picker.currentItem() is None:
            return
        self._fetch_entry(by_id[picker.currentItem().data(Qt.ItemDataRole.UserRole)])

    def _fetch_entry(self, entry: community.Entry) -> None:
        self._community_button.setEnabled(False)
        self._status.setText(f"Скачиваю «{entry.title}»…")
        self._entry_task = Task(community.fetch, entry)
        self._entry_task.done.connect(lambda result: self._add_entry(entry, result))
        self._entry_task.failed.connect(self._catalog_failed)
        self._entry_task.start()

    def _add_entry(self, entry: community.Entry, result: tuple[list[str], list[str]]) -> None:
        self._community_button.setEnabled(True)
        target = USER_LISTS.index(entry.target)
        if self._selector.currentIndex() != target:
            self._selector.setCurrentIndex(target)
        good, bad = result
        self._merge(good, bad)

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
