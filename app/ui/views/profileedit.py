"""Окно просмотра и правки профиля приложения.

Записанный профиль до сих пор был чёрным ящиком: в списке видно только
«адресов 12, TCP-портов 2», а что это за адреса и почему игра всё ещё
лагает — негде посмотреть. Между тем профиль — обычный набор портов и
адресов, и починить в нём лишний порт проще, чем переписывать заново.

Отсюда же создаётся профиль с нуля: иногда порты известны заранее (их
пишут на сайте игры), и записывать трафик ради них незачем.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.appprofile import Profile
from app.ui import dialogs
from app.ui.theme.tokens import COLORS, SPACE

log = logging.getLogger(__name__)

WIDTH = 560
LIST_HEIGHT = 92


def _numbers(text: str) -> list[int]:
    """Разбирает «443, 80 1024-1030» в список портов.

    Разделители какие угодно, диапазоны через дефис: переписывать сорок
    портов по одному в строку никто не станет.
    """
    found: list[int] = []
    for chunk in text.replace("\n", " ").replace(",", " ").replace(";", " ").split():
        if "-" in chunk[1:]:
            start, _, end = chunk.partition("-")
            try:
                first, last = int(start), int(end)
            except ValueError:
                continue
            if 0 < first <= last <= 65535:
                found.extend(range(first, last + 1))
            continue
        try:
            port = int(chunk)
        except ValueError:
            continue
        if 0 < port <= 65535:
            found.append(port)
    return sorted(set(found))


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


class ProfileEditor(dialogs.Dialog):
    """Правка профиля: имя, приложение, порты, адреса."""

    def __init__(self, parent: QWidget | None, profile: Profile, *, is_new: bool = False):
        super().__init__(
            parent,
            "Новый профиль" if is_new else f"Профиль «{profile.name}»",
            "Новый профиль" if is_new else profile.name,
            "Профиль — это фильтр по портам и адресам: winws не умеет "
            "отбирать трафик по процессу. Поэтому здесь всё, что в нём есть, "
            "и всё это можно поправить руками.",
        )
        self.setFixedWidth(WIDTH)
        self.profile = profile
        self.saved: Profile | None = None

        form = QVBoxLayout()
        form.setSpacing(SPACE["sm"])

        self._name = QLineEdit(profile.name)
        self._name.setPlaceholderText("название профиля")
        form.addWidget(self._field("Название", self._name))

        app_row = QHBoxLayout()
        app_row.setSpacing(SPACE["sm"])
        self._exe = QLineEdit(profile.exe)
        self._exe.setPlaceholderText("путь к .exe — нужен, чтобы включаться вместе с ним")
        app_row.addWidget(self._exe, 1)
        pick = QPushButton("Выбрать…")
        pick.clicked.connect(self._pick_exe)
        app_row.addWidget(pick)
        form.addWidget(self._label("Приложение"))
        form.addLayout(app_row)

        self._tcp = QLineEdit(self._ports_text(profile.tcp_ports))
        self._tcp.setPlaceholderText("например 443, 80")
        form.addWidget(self._field("Порты TCP", self._tcp))

        self._udp = QLineEdit(self._ports_text(profile.udp_ports))
        self._udp.setPlaceholderText("например 49152-65535")
        form.addWidget(self._field("Порты UDP", self._udp))

        form.addWidget(self._label("Адреса — по одному в строке"))
        self._addresses = QPlainTextEdit("\n".join(profile.addresses))
        self._addresses.setFixedHeight(LIST_HEIGHT)
        form.addWidget(self._addresses)

        self._auto = QCheckBox("Включать вместе с приложением")
        self._auto.setChecked(profile.auto_start)
        form.addWidget(self._auto)

        self._problem = QLabel("")
        self._problem.setWordWrap(True)
        self._problem.setStyleSheet(f"color: {COLORS['danger']};")
        self._problem.hide()
        form.addWidget(self._problem)

        self.insert_layout(form)
        self.add_action("Отмена")
        self.add_action("Сохранить", primary=True)

    # --- мелочи разметки -------------------------------------------------

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Muted")
        return label

    def _field(self, title: str, widget: QWidget) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._label(title))
        layout.addWidget(widget)
        return holder

    @staticmethod
    def _ports_text(ports: list[int]) -> str:
        """Сворачивает подряд идущие порты в диапазоны.

        У игр это бывают тысячи портов подряд — списком через запятую такое
        не прочитать и не поправить.
        """
        if not ports:
            return ""

        chunks: list[str] = []
        start = previous = ports[0]
        for port in ports[1:]:
            if port == previous + 1:
                previous = port
                continue
            chunks.append(str(start) if start == previous else f"{start}-{previous}")
            start = previous = port
        chunks.append(str(start) if start == previous else f"{start}-{previous}")
        return ", ".join(chunks)

    def _pick_exe(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Какое приложение пропускать через профиль",
            str(Path(self._exe.text()).parent) if self._exe.text() else "",
            "Программы (*.exe)",
        )
        if chosen:
            self._exe.setText(chosen)

    # --- сохранение ------------------------------------------------------

    def _answer_with(self, label: str) -> None:
        if label != "Сохранить":
            super()._answer_with(label)
            return

        problem = self._collect()
        if problem:
            self._problem.setText(problem)
            self._problem.show()
            return

        super()._answer_with(label)

    def _collect(self) -> str:
        """Собирает профиль из полей. Возвращает причину отказа или пустую строку."""
        name = self._name.text().strip()
        if not name:
            return "У профиля должно быть название."

        tcp = _numbers(self._tcp.text())
        udp = _numbers(self._udp.text())
        addresses = _lines(self._addresses.toPlainText())

        # Та же проверка, что у записи: фильтр без адресов или без портов
        # подошёл бы под любой пакет и накрыл бы весь трафик, а не игру.
        if not addresses:
            return "Нужен хотя бы один адрес — иначе фильтр накроет весь трафик."
        if not (tcp or udp):
            return "Нужен хотя бы один порт: TCP или UDP."

        self.saved = Profile(
            name=name,
            exe=self._exe.text().strip(),
            created_at=self.profile.created_at,
            tcp_ports=tcp,
            udp_ports=udp,
            addresses=addresses,
            source_strategy=self.profile.source_strategy,
            auto_start=self._auto.isChecked(),
        )
        return ""
