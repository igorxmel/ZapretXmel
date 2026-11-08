"""Управление обходом: общее для обзора и мини-окна.

Одни и те же кнопки живут в двух местах, поэтому логика у них одна: в двух копиях
поведение разошлось бы при первой же правке.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core import strategies
from app.ui import dialogs
from app.ui.controller import Controller, Status
from app.ui.theme.tokens import BRAND, COLORS, SPACE
from app.ui.widgets import Divider, PowerButton
from app.ui.workers import QuickCheckWorker

# Служба уже запущена, но winws нужно мгновение, чтобы начать перехватывать
# пакеты. Проверка без этой паузы мерила бы сеть ещё без обхода.
SETTLE_MS = 1500

CHECK_AS_IS = "Проверить как есть"
CHECK_ENABLE = "Включить и проверить"


def pending_strategy(status: Status, chosen: str) -> str:
    """Стратегия, которую выбрали в списке, но которая не работает. Иначе пусто.

    Обход могли поднять и снаружи, и тогда имени стратегии мы не знаем. Сверять
    не с чем, поэтому считаем, что расхождения нет.
    """
    if not chosen or not status.core_present:
        return ""
    if not status.is_active:
        return chosen
    if status.active_strategy and status.active_strategy != chosen:
        return chosen
    return ""


def strategy_hint(status: Status, chosen: str) -> str:
    """Подсказка под списком. Просто выбрать стратегию в нём недостаточно."""
    pending = pending_strategy(status, chosen)
    if not pending:
        return ""
    if status.is_active:
        return f"Сейчас работает «{status.active_strategy}», а «{pending}» только выбрана."
    return f"«{pending}» выбрана, но не включена."


def measured_note(status: Status, chosen: str) -> str:
    """Что именно измерила проверка.

    Сама она просто смотрит, открываются ли сервисы. Человек выбрал стратегию в
    списке, нажал проверку и решил, что результат про неё, хотя обход был выключен.
    """
    if not status.is_active:
        note = "Обход выключен: проверено без него."
    elif pending_strategy(status, chosen):
        note = f"Проверена «{status.active_strategy}», а не выбранная «{chosen}»."
    elif status.active_strategy:
        note = f"Проверена стратегия «{status.active_strategy}»."
    else:
        note = "Проверено с работающим обходом."

    if status.active_vpn:
        note += f" Трафик шёл через {status.active_vpn}: результат относится к нему."
    return note


class PowerTile(QWidget):
    """Круглый выключатель с подписью — одна управляемая штука."""

    toggled = pyqtSignal()

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        accent: str = COLORS["success"],
    ):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.button = PowerButton(accent=accent)
        self.button.clicked.connect(self.toggled.emit)
        layout.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._title = QLabel(title)
        self._title.setObjectName("ViewTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._title)

        self._state = QLabel("")
        self._state.setObjectName("Dim")
        self._state.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._state.setWordWrap(True)
        # Место под две строки держим сразу. Иначе подпись на кадр обрезалась, а вся карточка
        # подпрыгивала, когда длинное состояние приходило с первым опросом.
        self._state.ensurePolished()
        self._state.setMinimumHeight(2 * self._state.fontMetrics().lineSpacing())
        self._state.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._state)

    def apply(self, active: bool, enabled: bool, state: str) -> None:
        self.button.setChecked(active)
        self.button.set_available(enabled)
        self._state.setText(state)


class PowerPair(QWidget):
    """Две главные кнопки программы: обход и Telegram."""

    install_core_requested = pyqtSignal()
    install_proxy_requested = pyqtSignal()

    def __init__(self, controller: Controller, spacing: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller

        tiles = QHBoxLayout(self)
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(spacing)
        tiles.addStretch(1)

        self.bypass = PowerTile("Обход блокировок")
        self.bypass.toggled.connect(self._toggle_bypass)
        tiles.addWidget(self.bypass)

        # Прокси везде обозначен голубым — в трее, в боковом меню. Зелёное
        # кольцо здесь выбивалось из этого ряда.
        self.telegram = PowerTile("Telegram", accent=BRAND["telegram"])
        self.telegram.toggled.connect(self._toggle_telegram)
        tiles.addWidget(self.telegram)

        tiles.addStretch(1)

        controller.busy_changed.connect(self.bypass.button.set_busy)
        controller.telegram_busy.connect(self.telegram.button.set_busy)

    def _toggle_bypass(self) -> None:
        if not self.controller.status.core_present:
            self._offer_install("core")
            return
        self.controller.toggle()

    def _toggle_telegram(self) -> None:
        if not self.controller.status.telegram_installed:
            self._offer_install("proxy")
            return
        self.controller.toggle_telegram()

    def _offer_install(self, what: str) -> None:
        """Предлагает поставить то, чего ещё нет, и ставит с согласия.

        Гасить кнопку неправильно: человек жмёт главную кнопку программы и
        не получает ничего, даже объяснения. Но и ставить молча нельзя —
        нажатие на «включить» уходило качать полтора мегабайта с GitHub и
        перекидывало в другой раздел, о чём никто не просил.

        Поэтому оба нажатия ведут себя одинаково: вопрос, а потом установка
        там, где видно загрузку. Раньше ядро ставилось само, а прокси просто
        открывал свой раздел, и почему кнопки работают по-разному, понять
        было нельзя.
        """
        offers = {
            "core": (
                "Ядро zapret не установлено",
                "Скачать и установить его сейчас?",
                "Это сборка Flowseal — около полутора мегабайт с GitHub. "
                "Без неё включать нечего: все стратегии лежат именно в ней.",
            ),
            "proxy": (
                "Прокси для Telegram не установлен",
                "Скачать и установить его сейчас?",
                "Это tg-ws-proxy — около двадцати мегабайт с GitHub. "
                "Telegram Desktop не чинится обычными стратегиями, для него "
                "нужен отдельный локальный прокси.",
            ),
        }
        title, question, details = offers[what]

        if not dialogs.confirm(self, title, question, details, action="Скачать и установить"):
            return

        # Установка показывается там, где у неё есть полоса загрузки: файл
        # качается с GitHub, а он у части провайдеров открывается не сразу.
        if what == "core":
            self.install_core_requested.emit()
        else:
            self.install_proxy_requested.emit()

    def apply_status(self, status: Status) -> None:
        self.bypass.apply(active=status.is_active, enabled=True, state=self._bypass_state(status))
        paused = bool(status.vpn_paused) and not status.is_active
        self.bypass.button.set_paused(paused)
        self.bypass.button.setToolTip(
            "Обход ждёт, пока выключат VPN. Нажмите, чтобы выключить его совсем.\n"
            "Чтобы обход работал вместе с VPN, снимите галочку в «Состоянии»."
            if paused
            else ""
        )

        # Кнопка Telegram остаётся нажимаемой и без прокси: щелчок предлагает
        # его поставить — иначе непонятно, что делать дальше.
        if status.telegram_running:
            telegram_state = "прокси работает"
        elif status.telegram_installed:
            telegram_state = "прокси остановлен"
        else:
            telegram_state = "нажмите, чтобы установить"

        self.telegram.apply(active=status.telegram_running, enabled=True, state=telegram_state)

    @staticmethod
    def _bypass_state(status: Status) -> str:
        if not status.core_present:
            return "нажмите, чтобы установить ядро"
        if status.active_strategy:
            return f"стратегия «{status.active_strategy}»"
        # Подпись под кнопкой видна и в мини-окне, где других надписей о паузе нет.
        if status.vpn_paused:
            return "на паузе: работает VPN"
        if status.selected_strategy:
            return f"выбрана «{status.selected_strategy}»"
        return "стратегия не выбрана"


class StatusNotices(QWidget):
    """Предупреждения, без которых состояние на экране читается неверно."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])

        self._vpn = self._notice()
        layout.addWidget(self._vpn)

        # Чужая установка zapret пользуется той же службой, поэтому состояние
        # относится к ней, а не к нам. Промолчать об этом нельзя.
        self._foreign = self._notice()
        layout.addWidget(self._foreign)

        self.hide()

    @staticmethod
    def _notice() -> QLabel:
        label = QLabel("")
        label.setObjectName("Dim")
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {COLORS['warning']};")
        label.hide()
        return label

    def apply_status(self, status: Status) -> None:
        if status.vpn_paused and not status.is_active:
            text = (
                f"Обход на паузе, пока трафик идёт через {status.active_vpn or status.vpn_paused}. "
                "Когда VPN выключат, он включится сам."
            )
        elif status.is_active:
            text = (
                f"Трафик идёт через {status.active_vpn}. Сайты из списков обхода через VPN "
                "могут не открываться, а проверки измеряют VPN. Обход можно ставить на паузу "
                "на время VPN — галочка в «Состоянии»."
            )
        else:
            text = (
                f"Трафик идёт через {status.active_vpn}. Проверки сейчас измеряют VPN — "
                "выключите его перед подбором стратегии."
            )
        self._vpn.setText(text)
        vpn_shown = bool(status.active_vpn or (status.vpn_paused and not status.is_active))
        self._vpn.setVisible(vpn_shown)

        self._foreign.setText(
            f"На компьютере уже есть zapret: {status.foreign_install}. Служба у него и "
            "у нас одна и та же, поэтому состояние относится к нему. Включение "
            "обхода здесь переключит службу на эту программу — она сначала спросит."
        )
        self._foreign.setVisible(bool(status.foreign_install))

        self.setVisible(vpn_shown or bool(status.foreign_install))


class QuickPanel(QWidget):
    """Выбор стратегии и быстрая проверка.

    Порядок на экране такой же, как порядок действий: выбрать, включить, проверить.
    """

    # Появился ответ проверки: в маленьком окне он мог оказаться за краем.
    answer_shown = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self._quick: QuickCheckWorker | None = None
        # Выбор программы, который список уже показал. См. `_sync_strategy_box`.
        self._seen_selected = controller.settings.selected_strategy

        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(SPACE["sm"])

        # Смена стратегии — единственное, за чем сюда возвращаются чаще
        # всего. Раньше ради неё приходилось уходить на другой экран, хотя
        # всё, что нужно, — выбрать из списка и нажать.
        body.addWidget(QLabel("Стратегия обхода"))

        self._strategy_box = QComboBox()
        self._strategy_box.currentIndexChanged.connect(self._show_hint)
        body.addWidget(self._strategy_box)

        self._hint = QLabel("")
        self._hint.setObjectName("Muted")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"color: {COLORS['warning']};")
        self._hint.hide()
        body.addWidget(self._hint)

        # Называем делом, а не намерением: рядом на экране «Стратегии» стоит
        # «Применить и включить», и разница между двумя «Применить» была
        # загадкой — на самом деле её нет.
        self._apply_button = QPushButton("Применить и включить")
        self._apply_button.clicked.connect(self._apply_strategy)
        body.addWidget(self._apply_button)

        body.addWidget(Divider())

        # Главный вопрос человека, включившего обход, — «ну и работает ли?».
        # Подбор отвечает на него за минуты, диагностика проверяет систему, а
        # не сервисы; здесь — ответ за несколько секунд.
        self._check_button = QPushButton("Проверить, работает ли сейчас")
        self._check_button.clicked.connect(self._check_clicked)
        body.addWidget(self._check_button)

        # Человеку не нужно знать, чем проверка отличается от подбора: нужно, чтобы заработало.
        self._repair_button = QPushButton("Не работает? Починить")
        self._repair_button.setToolTip(
            "Проверит сервисы, попробует лучшие стратегии, при необходимости переберёт все и "
            "включит подошедшую. На это время обход выключается."
        )
        self._repair_button.clicked.connect(self._repair_clicked)
        body.addWidget(self._repair_button)

        self._check_result = QLabel("")
        self._check_result.setObjectName("Dim")
        self._check_result.setWordWrap(True)
        body.addWidget(self._check_result)

        # Сторож проверяет сам, и об этом стоит знать, не нажимая ничего.
        self._watch_line = QLabel("")
        self._watch_line.setWordWrap(True)
        body.addWidget(self._watch_line)

        flow = controller.repair
        flow.running_changed.connect(self._repair_running)
        flow.progress.connect(lambda text: self._say_check(text, COLORS["text_muted"]))
        flow.finished.connect(self._say_check)

    # --- стратегия --------------------------------------------------------

    def reload(self) -> None:
        self._fill_strategies()
        self._show_hint()

    def _fill_strategies(self) -> None:
        """Заполняет список: избранные наверх, выбранная — текущей.

        Показывается именно выбранная программой стратегия, а не та, что
        осталась в списке с прошлого раза: подбор меняет выбор на своём
        экране, и на обзоре должна быть видна она же.
        """
        names = [spec.name for spec in strategies.load_all()]
        favorites = self.controller.settings.favorites
        names.sort(key=lambda name: name not in favorites)

        self._strategy_box.blockSignals(True)
        self._strategy_box.clear()
        for name in names:
            self._strategy_box.addItem(("★ " if name in favorites else "") + name, name)

        self._seen_selected = self.controller.settings.selected_strategy
        index = self._strategy_box.findData(self._seen_selected)
        if index >= 0:
            self._strategy_box.setCurrentIndex(index)
        self._strategy_box.blockSignals(False)

        self._apply_button.setEnabled(bool(names))

    def _sync_strategy_box(self) -> None:
        """Подхватывает смену стратегии, сделанную на другом экране.

        Срабатывает, только когда выбор программы действительно изменился. Раньше
        список сверялся с ним при каждом опросе: стоило убрать фокус, и стратегия,
        выбранная, но ещё не применённая, сама откатывалась назад через секунды.

        Пока список раскрыт или в фокусе, не трогаем: человек выбирает, и
        подменять выбор под рукой нельзя.
        """
        if self._strategy_box.hasFocus() or self._strategy_box.view().isVisible():
            return

        wanted = self.controller.settings.selected_strategy
        if not wanted or wanted == self._seen_selected:
            return
        self._seen_selected = wanted

        index = self._strategy_box.findData(wanted)
        if index < 0:
            self._fill_strategies()
            return

        self._strategy_box.blockSignals(True)
        self._strategy_box.setCurrentIndex(index)
        self._strategy_box.blockSignals(False)

    @property
    def answer(self) -> QLabel:
        return self._check_result

    def _chosen(self) -> str:
        return self._strategy_box.currentData() or ""

    def _apply_strategy(self) -> None:
        name = self._chosen()
        if not name:
            return

        self.controller.select_strategy(name)
        if self.controller.status.is_active:
            self.controller.restart()
        else:
            self.controller.start()
        self._show_hint()

    def _show_hint(self) -> None:
        """Пока выбор не применён, об этом говорит и подпись, и сама кнопка."""
        status = self.controller.status
        hint = strategy_hint(status, self._chosen())
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))

        wanted = "Primary" if hint else ""
        if self._apply_button.objectName() != wanted:
            self._apply_button.setObjectName(wanted)
            self._apply_button.style().unpolish(self._apply_button)
            self._apply_button.style().polish(self._apply_button)

    # --- проверка ---------------------------------------------------------

    def _check_clicked(self) -> None:
        """Проверка выбранной, но не включённой стратегии ничего бы о ней не сказала."""
        if self._quick is not None and self._quick.isRunning():
            return

        pending = pending_strategy(self.controller.status, self._chosen())
        if not pending:
            self._run_quick_check()
            return

        answer = self._ask_about_pending(pending)
        if answer == CHECK_AS_IS:
            self._run_quick_check()
        elif answer == CHECK_ENABLE:
            self._check_button.setEnabled(False)
            self._say_check(f"Включаю «{pending}»…", COLORS["text_muted"])
            self._apply_strategy()
            QTimer.singleShot(SETTLE_MS, self._run_quick_check)

    def _repair_clicked(self) -> None:
        flow = self.controller.repair
        if flow.running:
            flow.cancel()
            return

        reason = flow.refusal()
        if reason:
            self._say_check(reason, COLORS["warning"])
            return

        if dialogs.confirm(
            self,
            "Починить",
            "Подобрать рабочую стратегию и включить её?",
            "Обычно это минута, но если лучшие стратегии не подойдут, программа переберёт все, "
            "а это несколько минут. На это время обход выключается. Если ничего не подойдёт, "
            "вернётся прежняя стратегия.",
            action="Починить",
        ):
            flow.start()

    def _repair_running(self, running: bool) -> None:
        self._repair_button.setText("Остановить" if running else "Не работает? Починить")
        self._check_button.setEnabled(not running)
        self._apply_button.setEnabled(not running and self._strategy_box.count() > 0)

    def _ask_about_pending(self, pending: str) -> str:
        dialog = dialogs.Dialog(
            self,
            "Стратегия не включена",
            f"«{pending}» выбрана, но не включена.",
            "Проверка измеряет то, что работает прямо сейчас, а не то, что выбрано в списке. "
            "Чтобы проверить эту стратегию, её нужно включить.",
        )
        dialog.add_action(CHECK_AS_IS)
        dialog.add_action(CHECK_ENABLE, primary=True)
        return dialog.ask()

    def _run_quick_check(self) -> None:
        if self._quick is not None and self._quick.isRunning():
            return

        self._check_button.setEnabled(False)
        self._say_check("Проверяю сервисы…", COLORS["text_muted"])

        settings = self.controller.settings
        self._quick = QuickCheckWorker(
            timeout=settings.probe_timeout, parallel=settings.probe_parallel
        )
        self._quick.done.connect(self._quick_done)
        self._quick.failed.connect(lambda text: self._say_check(text, COLORS["danger"]))
        self._quick.finished.connect(lambda: self._check_button.setEnabled(True))
        self._quick.start()

    def _quick_done(self, check) -> None:
        self.controller.remember_check(check)
        if check.everything_works:
            colour = COLORS["success"]
        elif check.working:
            colour = COLORS["warning"]
        else:
            colour = COLORS["danger"]

        verdict = check.verdict[:1].upper() + check.verdict[1:]
        note = measured_note(self.controller.status, self._chosen())
        self._say_check(f"{verdict}\n{note}", colour)

    def _say_check(self, text: str, colour: str) -> None:
        self._check_result.setStyleSheet(f"color: {colour};")
        self._check_result.setText(text)
        self.answer_shown.emit()

    def _say_watch(self) -> None:
        """Строка о последней проверке — своей или сторожевой."""
        when = self.controller.last_check_at
        check = self.controller.last_check
        if when is None or check is None:
            self._watch_line.setText("Проверки ещё не было")
            self._watch_line.setStyleSheet(f"color: {COLORS['text_muted']};")
            return

        minutes = int((datetime.now() - when).total_seconds() // 60)
        if minutes < 1:
            ago = "только что"
        elif minutes < 60:
            ago = f"{minutes} мин назад"
        else:
            ago = f"{minutes // 60} ч назад"

        if check.everything_works:
            self._watch_line.setText(f"Проверено {ago}: всё работало")
            self._watch_line.setStyleSheet(f"color: {COLORS['success']};")
        elif check.working:
            self._watch_line.setText(f"Проверено {ago}: не работает {', '.join(check.broken)}")
            self._watch_line.setStyleSheet(f"color: {COLORS['warning']};")
        else:
            self._watch_line.setText(f"Проверено {ago}: не работало ничего")
            self._watch_line.setStyleSheet(f"color: {COLORS['danger']};")

    def apply_status(self, _status: Status) -> None:
        self._say_watch()
        self._sync_strategy_box()
        self._show_hint()
