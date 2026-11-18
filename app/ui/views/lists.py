"""Экран пользовательских списков доменов и адресов."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import community, lists
from app.core.lists import USER_LISTS, UserList
from app.ui import dialogs
from app.ui.controller import Controller
from app.ui.strategy_parts import FlowLayout, tinted
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, TabStrip, view_header
from app.ui.workers import Task

ADD_FROM_CATALOG = "Добавить к моим"

# Свой цвет у каждого списка — точка в карточке слева и тон тегов справа.
LIST_COLOURS = {
    "list-general-user.txt": "#4f8ff0",
    "list-exclude-user.txt": "#e0a030",
    "ipset-exclude-user.txt": "#a97ff0",
}


class ListButton(QPushButton):
    """Карточка списка слева: точка цвета, название, счётчик и короткое пояснение."""

    def __init__(self, user_list: UserList, colour: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.user_list = user_list
        self.setObjectName("ListButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(250)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        column = QVBoxLayout(self)
        column.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        column.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(SPACE["sm"])
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {colour}; background: transparent;")
        head.addWidget(dot)
        title = QLabel(user_list.title)
        title.setObjectName("ListButtonTitle")
        head.addWidget(title)
        head.addStretch(1)
        self._count = QLabel("0")
        self._count.setObjectName("CountBadge")
        head.addWidget(self._count)
        column.addLayout(head)
        hint = QLabel(user_list.hint)
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        column.addWidget(hint)
        for label in (dot, title, self._count, hint):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_count(self, count: int) -> None:
        self._count.setText(str(count))

    def sizeHint(self):  # noqa: N802 — имя задано Qt
        return self.layout().sizeHint()


class TagChip(QFrame):
    """Запись списка таблеткой с крестиком."""

    removed = pyqtSignal(str)

    def __init__(self, text: str, colour: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TagChip")
        self.setStyleSheet(
            f"QFrame#TagChip {{ background: {tinted(colour, 30)};"
            f" border: 1px solid {tinted(colour, 90)}; border-radius: 6px; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE["sm"], 2, 2, 2)
        row.setSpacing(2)
        label = QLabel(text)
        label.setStyleSheet("background: transparent;")
        row.addWidget(label)
        close = QToolButton()
        close.setText("×")
        close.setObjectName("TagClose")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("Убрать запись")
        close.clicked.connect(lambda: self.removed.emit(text))
        row.addWidget(close)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


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

        columns = QHBoxLayout()
        columns.setSpacing(SPACE["lg"])
        columns.addLayout(self._build_list_column(), 0)
        columns.addWidget(self._build_editor_card(), 1)
        layout.addLayout(columns, 1)

    # --- левая колонка: какие списки есть ------------------------------------

    def _build_list_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(SPACE["sm"])
        self._list_buttons: list[ListButton] = []
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, user_list in enumerate(USER_LISTS):
            button = ListButton(user_list, LIST_COLOURS[user_list.filename])
            button.clicked.connect(lambda _, chosen=index: self._switch_list(chosen))
            group.addButton(button)
            column.addWidget(button)
            self._list_buttons.append(button)
        self._list_buttons[0].setChecked(True)
        column.addStretch(1)
        return column

    # --- правая карточка: сам список ----------------------------------------

    def _build_editor_card(self) -> Card:
        card = Card()
        body = card.body()

        head = QHBoxLayout()
        head.setSpacing(SPACE["sm"])
        self._title = QLabel(self._current.title)
        self._title.setObjectName("ListTitle")
        head.addWidget(self._title)
        self._count = QLabel("0")
        self._count.setObjectName("CountBadge")
        head.addWidget(self._count)
        head.addStretch(1)
        # Теги — чтобы видеть каждую запись отдельно и убрать лишнюю крестиком;
        # текст — чтобы вставить сразу пачку из чата.
        self._mode = TabStrip([("tags", "Теги"), ("text", "Текст")])
        self._mode.changed.connect(self._switch_mode)
        head.addWidget(self._mode)
        body.addLayout(head)

        self._hint = QLabel(self._current.hint)
        self._hint.setObjectName("Muted")
        self._hint.setWordWrap(True)
        body.addWidget(self._hint)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_tags_page())
        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText("По одной записи на строку")
        self._editor.textChanged.connect(self._editor_changed)
        self._pages.addWidget(self._editor)
        body.addWidget(self._pages, 1)

        footer = QHBoxLayout()
        footer.setSpacing(SPACE["sm"])
        save_button = QPushButton("Сохранить")
        save_button.setObjectName("Primary")
        save_button.clicked.connect(self._save)
        footer.addWidget(save_button)

        reload_button = QPushButton("Отменить правки")
        reload_button.clicked.connect(self.reload)
        footer.addWidget(reload_button)

        # Готовые списки от других — из ветки community-lists этого репозитория.
        self._community_button = QPushButton("Каталог сообщества…")
        self._community_button.setToolTip(
            "Готовые списки доменов, которые прислали другие пользователи и проверил автор. "
            "Выбранный добавится к вашим записям в редакторе — сохраняете вы сами"
        )
        self._community_button.clicked.connect(self._open_catalog)
        footer.addWidget(self._community_button)

        # Файлы и перенос — реже, поэтому в меню: пять кнопок в ряд не помещались.
        files = QPushButton("Файл")
        menu = QMenu(files)
        load = menu.addAction("Добавить из файла…")
        load.setToolTip(
            "Записи из файла .txt добавятся к уже имеющимся. Ссылки сводятся к доменам, "
            "комментарии и повторы пропускаются"
        )
        load.triggered.connect(self._load_file)
        menu.addAction("Сохранить в файл…").triggered.connect(self._export_file)
        menu.addSeparator()
        # Для тех, кто переезжает с консольной сборки: ищет такие же *-user.txt в чужой
        # папке. Если там ничего не дописывали — переносить нечего, это не поломка.
        menu.addAction("Импорт из другой папки zapret…").triggered.connect(self._import)
        menu.setToolTipsVisible(True)
        files.setMenu(menu)
        footer.addWidget(files)

        footer.addStretch(1)
        body.addLayout(footer)

        # Отдельной строкой: в ряду с кнопками длинное сообщение сжималось в три строки.
        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        body.addWidget(self._status)
        return card

    def _build_tags_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SPACE["sm"])

        self._new_entry = QLineEdit()
        self._new_entry.setPlaceholderText("Добавить запись — Enter")
        self._new_entry.returnPressed.connect(self._add_typed)
        column.addWidget(self._new_entry)

        self._tags_box = QWidget()
        self._tags_box.setObjectName("Flow")
        self._tags = FlowLayout(self._tags_box, spacing=SPACE["sm"])
        scroll = QScrollArea()
        scroll.setObjectName("SectionsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("Flow")
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(self._tags_box)
        holder_layout.addStretch(1)
        scroll.setWidget(holder)
        column.addWidget(scroll, 1)

        self._tags_empty = QLabel("Записей пока нет. Впишите домен выше и нажмите Enter.")
        self._tags_empty.setObjectName("Muted")
        self._tags_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self._tags_empty)
        return page

    # --- теги ---------------------------------------------------------------

    def _switch_mode(self, mode: str) -> None:
        self._pages.setCurrentIndex(0 if mode == "tags" else 1)
        if mode == "tags":
            self._rebuild_tags()

    def _editor_changed(self) -> None:
        entries = self._editor_entries()
        self._count.setText(str(len(entries)))
        if self._pages.currentIndex() == 0:
            self._rebuild_tags()

    def _rebuild_tags(self) -> None:
        while self._tags.count():
            item = self._tags.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().deleteLater()
        entries = self._editor_entries()
        colour = LIST_COLOURS[self._current.filename]
        for entry in entries:
            valid = lists.validate(entry, self._current.kind)
            tag = TagChip(entry, colour if valid else COLORS["danger"])
            if not valid:
                tag.setToolTip("Не похоже на запись этого списка — при сохранении отбросится")
            tag.removed.connect(self._remove_entry)
            self._tags.addWidget(tag)
        self._tags_empty.setVisible(not entries)
        self._tags_box.updateGeometry()

    def _remove_entry(self, entry: str) -> None:
        kept = [line for line in self._editor_entries() if line != entry]
        self._editor.setPlainText("\n".join(kept))

    def _add_typed(self) -> None:
        good, bad = lists.parse_import(self._new_entry.text(), self._current.kind)
        if bad and not good:
            self._status.setStyleSheet(f"color: {COLORS['warning']};")
            self._status.setText(f"Не похоже на запись этого списка: {bad[0]}")
            return
        self._new_entry.clear()
        self._merge(good, bad)

    def reload(self) -> None:
        """Перечитывает текущий список с диска."""
        lists.ensure_user_lists()
        content = lists.read(self._current)
        # Заглушку программа подставляет сама, когда список пуст: winws не любит пустые
        # файлы. Человеку она ни к чему и выглядела как чужая запись.
        entries = [e for e in content.entries if e != self._current.placeholder]

        self._title.setText(self._current.title)
        self._editor.setPlainText("\n".join(entries))
        self._hint.setText(self._current.hint)
        self._status.setStyleSheet(f"color: {COLORS['text_muted']};")
        self._refresh_counts()

        if content.invalid:
            self._status.setText(
                f"В файле есть нечитаемые строки ({len(content.invalid)}) — "
                "при сохранении они будут удалены"
            )
        else:
            self._status.setText("")

    def _refresh_counts(self) -> None:
        for button in self._list_buttons:
            saved = [
                e for e in lists.read(button.user_list).entries
                if e != button.user_list.placeholder
            ]
            button.set_count(len(saved))

    def _switch_list(self, index: int) -> None:
        if 0 <= index < len(USER_LISTS):
            self._current = USER_LISTS[index]
            self._list_buttons[index].setChecked(True)
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
        self._refresh_counts()

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
        if self._current is not USER_LISTS[target]:
            self._switch_list(target)
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
