"""Экран настроек: режим запуска, игровой фильтр, IP-набор, фейки, автозапуск."""

from __future__ import annotations

import contextlib
import logging
import sys
import winreg
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core import fakes, gamefilter, ipset
from app.core.gamefilter import GameFilter
from app.ui.controller import Controller
from app.ui.theme.tokens import COLORS, SPACE
from app.ui.widgets import Card, view_header

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

        columns = QHBoxLayout()
        columns.setSpacing(SPACE["lg"])
        columns.addWidget(self._build_app_card(), 1)
        columns.addWidget(self._build_bundle_card(), 1)
        layout.addLayout(columns, 1)

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

        self._start_minimized = QCheckBox("Запускать свёрнутым в трей")
        self._start_minimized.toggled.connect(self._save_flags)
        body.addWidget(self._start_minimized)

        self._minimize_to_tray = QCheckBox("Сворачивать в трей вместо закрытия")
        self._minimize_to_tray.toggled.connect(self._save_flags)
        body.addWidget(self._minimize_to_tray)

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

        welcome = QPushButton("Показать окно знакомства")
        welcome.setToolTip("То самое окно с шагами настройки, что открывается при первом запуске")
        welcome.clicked.connect(self._show_welcome)
        body.addWidget(welcome)

        body.addStretch(1)
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
            self._start_minimized.setChecked(settings.start_minimized)
            self._minimize_to_tray.setChecked(settings.minimize_to_tray)
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
        settings.start_minimized = self._start_minimized.isChecked()
        settings.minimize_to_tray = self._minimize_to_tray.isChecked()
        settings.probe_timeout = self._timeout.value()
        settings.probe_parallel = self._parallel.value()
        settings.save()

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
