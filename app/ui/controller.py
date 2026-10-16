"""Связующее звено между интерфейсом и логикой.

Экраны не управляют обходом напрямую — они просят об этом контроллер и слушают
его сигналы. Благодаря этому состояние «включено/выключено» всегда одно на всё
приложение: дашборд, список стратегий и значок в трее не могут разойтись.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from app.core import coreinfo, foreign, service, strategies, telegram, watch, winws
from app.core.batfile import StrategySpec
from app.core.config import Settings
from app.core.diagnostics import vpn
from app.core.telegram import TelegramProxy
from app.core.winws import WinwsProcess
from app.ui.workers import Task

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 3000


@dataclass
class Status:
    """Снимок состояния обхода для интерфейса."""

    core_present: bool = False
    core_version: str = ""
    strategy_count: int = 0

    service_state: str = "not_installed"
    service_strategy: str = ""
    winws_count: int = 0
    run_mode: str = "service"
    active_strategy: str = ""
    selected_strategy: str = ""
    active_vpn: str = ""
    # Папка другой установки zapret, если она есть: служба у неё и у нас одна
    # и та же, и без этого состояние на экране относилось бы к ней молча.
    foreign_install: str = ""
    active_profile: str = ""
    # Что сделать с профилем приложения по итогам опроса: («start»|«stop», имя).
    profile_action: tuple[str, str] = ("", "")
    telegram_installed: bool = False
    telegram_running: bool = False
    log_tail: list[str] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.winws_count > 0

    @property
    def state_label(self) -> str:
        if not self.core_present:
            return "ядро не установлено"
        if not self.is_active:
            return "обход выключен"
        if self.run_mode == "service":
            return "обход работает как служба"
        return "обход работает как процесс"


class Controller(QObject):
    """Единая точка управления обходом."""

    status_changed = pyqtSignal(object)
    busy_changed = pyqtSignal(bool)
    error = pyqtSignal(str)
    message = pyqtSignal(str)
    log_line = pyqtSignal(str)
    # Путь к чужой установке, которую затронет включение обхода. Решение за
    # человеком, поэтому контроллер только сообщает, а спрашивает интерфейс.
    foreign_conflict = pyqtSignal(str)
    # Сообщение сторожа и признак того, что он сам переключил стратегию.
    watch_alert = pyqtSignal(str, bool)
    # Результат любой быстрой проверки — своей или сторожевой.
    check_done = pyqtSignal(object)

    def __init__(self, settings: Settings, parent: QObject | None = None):
        super().__init__(parent)
        self.settings = settings
        self.status = Status()
        self._process: WinwsProcess | None = None
        # Профиль приложения поднимается отдельным экземпляром winws: так
        # основная стратегия остаётся нетронутой, а сломанный профиль
        # выключается одной кнопкой.
        self._profile_process: WinwsProcess | None = None
        self._profile_name = ""
        self._busy = False

        # Прокси для Telegram живёт столько же, сколько приложение: иначе он
        # останавливался бы при каждом переключении экрана.
        self.telegram = TelegramProxy(on_output=self.log_line.emit)

        self._poll_task: Task | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.poll)

        # Сторож: своя задача и свой таймер. Проверка ходит в сеть и длится
        # секунды, поэтому опрос состояния её ждать не должен.
        self._watch_worker = None
        self._watch_tried: list[str] = []
        self.last_check: object | None = None
        self.last_check_at: datetime | None = None
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self.watch_now)

    def start_polling(self) -> None:
        self.poll()
        self._timer.start()
        self.restart_watch()

    def stop_polling(self) -> None:
        self._timer.stop()
        self._watch_timer.stop()
        if self._poll_task is not None and self._poll_task.isRunning():
            self._poll_task.wait(3000)

    # --- сторож ---------------------------------------------------------

    def restart_watch(self) -> None:
        """Перезапускает таймер сторожа по текущим настройкам."""
        self._watch_timer.stop()
        if not self.settings.watch_enabled:
            return

        minutes = max(1, self.settings.watch_interval_minutes)
        self._watch_timer.start(minutes * 60 * 1000)
        log.info("Сторож проверяет обход раз в %d мин", minutes)

    def watch_now(self) -> None:
        """Запускает проверку сторожа, если предыдущая уже закончилась."""
        from app.ui.workers import QuickCheckWorker

        if self._watch_worker is not None and self._watch_worker.isRunning():
            return
        if not self.status.core_present:
            return

        self._watch_worker = QuickCheckWorker(
            timeout=self.settings.probe_timeout, parallel=self.settings.probe_parallel
        )
        self._watch_worker.done.connect(self._watch_result)
        self._watch_worker.start()

    def remember_check(self, check) -> None:
        """Запоминает результат проверки, откуда бы он ни пришёл."""
        self.last_check = check
        self.last_check_at = datetime.now()
        self.check_done.emit(check)

    def _watch_result(self, check) -> None:
        """Решает, что делать с результатом проверки."""
        self.remember_check(check)
        status = self.status
        decision = watch.decide(
            check.broken,
            active=status.is_active,
            vpn=bool(status.active_vpn),
            autoswitch=self.settings.watch_autoswitch,
            favorites=list(self.settings.favorites),
            current=status.active_strategy or self.settings.selected_strategy,
            tried=self._watch_tried,
        )

        if not decision.broken:
            # Всё в порядке — счётчик попыток можно обнулить: следующая
            # поломка начнётся с чистого листа.
            self._watch_tried.clear()
            return

        if decision.quiet:
            return

        self.watch_alert.emit(decision.message, bool(decision.switch_to))
        if not decision.switch_to:
            return

        self._watch_tried.append(decision.switch_to)
        self.select_strategy(decision.switch_to)
        self.restart()

    # --- состояние ------------------------------------------------------

    def _gather(self) -> Status:
        """Собирает состояние системы.

        Ходит в `sc`, перебирает процессы и читает файлы ядра, поэтому
        вызывается только из фонового потока — из потока интерфейса это
        подвешивало окно на несколько сотен миллисекунд каждый опрос.
        """
        info = coreinfo.describe()
        service_state = service.query_state()
        running = winws.count_instances()

        # Чужую установку ищем только когда есть по чему искать: без службы и
        # без запущенных winws следов всё равно нет, а опрос идёт каждые
        # несколько секунд.
        stranger = (
            foreign.detect() if service_state != "not_installed" or running else None
        )

        own_process_alive = self._process is not None and self._process.is_alive()
        status = Status(
            core_present=info.present,
            core_version=info.version,
            strategy_count=info.strategy_count,
            service_state=service_state,
            service_strategy=service.installed_strategy(),
            winws_count=running,
            run_mode="process" if own_process_alive else "service",
            selected_strategy=self.settings.selected_strategy,
            active_vpn=tunnel.adapter if (tunnel := vpn.detect_fast()) else "",
            foreign_install=str(stranger.root) if stranger else "",
            telegram_installed=telegram.is_installed(),
            telegram_running=self.telegram.is_running(),
            active_profile=self._profile_name if self._profile_alive() else "",
            profile_action=self._decide_about_profiles(),
            log_tail=list(self._process.output) if self._process else [],
        )

        if own_process_alive:
            status.active_strategy = self.settings.selected_strategy
        elif service_state == "running":
            status.active_strategy = status.service_strategy

        return status

    def _publish(self, status: Status) -> None:
        self.status = status
        self.status_changed.emit(status)

        action, name = status.profile_action
        if action:
            self._follow_apps(action, name)

    def refresh(self) -> Status:
        """Синхронно перечитывает состояние — после действий пользователя."""
        status = self._gather()
        self._publish(status)
        return status

    def poll(self) -> None:
        """Фоновое обновление состояния по таймеру.

        Пока предыдущий опрос не закончился, новый не запускается: на медленной
        машине `sc query` иногда отвечает дольше периода таймера.
        """
        if self._poll_task is not None and self._poll_task.isRunning():
            return

        task = Task(self._gather)
        task.done.connect(self._publish)
        task.failed.connect(lambda message: log.warning("Опрос состояния не удался: %s", message))
        self._poll_task = task
        task.start()

    # --- управление -----------------------------------------------------

    def selected_spec(self) -> StrategySpec | None:
        """Разобранная выбранная стратегия; при пустом выборе — первая из списка."""
        name = self.settings.selected_strategy
        if name:
            spec = strategies.load_one(name)
            if spec is not None:
                return spec

        available = strategies.load_all()
        if not available:
            return None

        self.settings.selected_strategy = available[0].name
        self.settings.save()
        return available[0]

    def select_strategy(self, name: str) -> None:
        self.settings.selected_strategy = name
        self.settings.save()
        self.refresh()

    def start(self, replace_foreign: bool = False) -> None:
        """Включает обход выбранным способом — службой или обычным процессом."""
        spec = self.selected_spec()
        if spec is None:
            self.error.emit("Не выбрана стратегия — сначала установите ядро.")
            return

        # Чужую установку нельзя подвинуть молча: служба будет пересоздана на
        # наш путь, а в режиме процесса её winws вдобавок снимут. Спрашиваем —
        # и только потом трогаем.
        if self.status.foreign_install and not replace_foreign:
            self.foreign_conflict.emit(self.status.foreign_install)
            return

        self._set_busy(True)
        try:
            if self.settings.run_mode == "service":
                service.install(spec)
                self.message.emit(f"Служба запущена со стратегией «{spec.name}»")
            else:
                winws.kill_all()
                self._process = WinwsProcess(on_output=self.log_line.emit)
                self._process.start(spec)
                if not winws.wait_until_ready():
                    raise RuntimeError("процесс winws не запустился — смотрите раздел «Логи»")
                self.message.emit(f"Обход запущен со стратегией «{spec.name}»")
        except Exception as error:  # noqa: BLE001 — причину показываем пользователю
            log.exception("Не удалось включить обход")
            self.error.emit(str(error))
        finally:
            self._set_busy(False)
            self.refresh()

    def stop(self) -> None:
        """Выключает обход: снимает службу и все процессы winws."""
        self._set_busy(True)
        try:
            if self._process is not None:
                self._process.stop()
                self._process = None

            if service.is_installed():
                service.remove()

            winws.kill_all()
            self.message.emit("Обход выключен")
        except Exception as error:  # noqa: BLE001 — причину показываем пользователю
            log.exception("Не удалось выключить обход")
            self.error.emit(str(error))
        finally:
            self._set_busy(False)
            self.refresh()

    def toggle(self) -> None:
        self.stop() if self.status.is_active else self.start()

    def _decide_about_profiles(self) -> tuple[str, str]:
        """Что сделать с профилем приложения: («start»|«stop», имя профиля).

        Решается в фоновом опросе: перебор процессов стоит денег, а в потоке
        интерфейса он подвешивал бы окно каждые несколько секунд. Само же
        действие выполняет интерфейс — запуск winws трогает состояние
        контроллера.
        """
        from app.core import appprofile, appwatch

        profiles = [item for item in appprofile.load_all() if item.auto_start]
        if not profiles:
            return ("", "")

        running = appwatch.running_executables()
        for profile in profiles:
            action = appwatch.decide(
                profile.exe,
                auto=True,
                profile_active=self._profile_name == profile.name and self._profile_alive(),
                running=running,
            )
            if action:
                return (action, profile.name)

        return ("", "")

    def _follow_apps(self, action: str, name: str) -> None:
        from app.core import appprofile

        if action == "stop":
            log.info("Приложение профиля «%s» закрылось — гашу профиль", name)
            self.stop_profile()
            self.message.emit(f"Профиль «{name}» выключен вместе с приложением")
            return

        profile = next((item for item in appprofile.load_all() if item.name == name), None)
        if profile is None:
            return

        log.info("Приложение профиля «%s» запущено — поднимаю профиль", name)
        self.start_profile(profile)

    def _profile_alive(self) -> bool:
        return self._profile_process is not None and self._profile_process.is_alive()

    def start_profile(self, profile) -> None:
        """Поднимает профиль приложения вторым экземпляром winws."""
        from app.core import appprofile

        spec = self.selected_spec()
        if spec is None:
            self.error.emit("Сначала выберите стратегию — из неё берётся способ обхода.")
            return

        self.stop_profile()
        try:
            built = appprofile.as_spec(profile, spec)
            process = WinwsProcess(on_output=self.log_line.emit)
            process.start(built)
            if not winws.wait_until_ready():
                raise RuntimeError("процесс winws не поднялся — смотрите раздел «Логи»")
        except Exception as error:  # noqa: BLE001 — причину показываем пользователю
            log.exception("Не удалось включить профиль приложения")
            self.error.emit(str(error))
            return

        self._profile_process = process
        self._profile_name = profile.name
        self.message.emit(f"Профиль «{profile.name}» включён")
        self.refresh()

    def stop_profile(self) -> None:
        if self._profile_process is not None:
            self._profile_process.stop()
            self._profile_process = None
        self._profile_name = ""
        self.refresh()

    def toggle_telegram(self) -> None:
        """Включает или выключает прокси для Telegram."""
        try:
            if self.telegram.is_running():
                self.telegram.stop()
                self.message.emit("Прокси для Telegram остановлен")
            else:
                state = self.telegram.start()
                self.message.emit(
                    f"Прокси слушает {state.host}:{state.port} — "
                    "нажмите «Открыть в Telegram» на вкладке Telegram"
                )
        except Exception as error:  # noqa: BLE001 — причину показываем пользователю
            log.exception("Не удалось переключить прокси для Telegram")
            self.error.emit(str(error))
        finally:
            self.refresh()

    def relocate(self, target):
        """Переносит установку в другую папку и возвращает новый путь к программе.

        Путь нужен интерфейсу: после переезда .exe работает ещё старый файл,
        и программу надо перезапустить с нового места.

        Обход гасится до переноса: файлы ядра заняты запущенным winws, а служба
        помнит абсолютный путь к нему. После переезда обход поднимается заново
        с новым путём, если был включён.
        """
        from pathlib import Path

        from app.core import location

        was_active = self.status.is_active
        telegram_was_running = self.telegram.is_running()

        self._set_busy(True)
        try:
            if telegram_was_running:
                self.telegram.stop()
            if was_active:
                self.stop()

            result = location.relocate(Path(target))
            self.message.emit(f"Папка установки: {result.target} ({result.summary})")
        except Exception as error:  # noqa: BLE001 — причину показываем пользователю
            log.exception("Не удалось перенести установку")
            self.error.emit(str(error))
            return None
        finally:
            self._set_busy(False)

        if was_active:
            self.start(replace_foreign=True)
        if telegram_was_running and telegram.is_installed():
            self.toggle_telegram()
        self.refresh()
        return result.executable

    def restart(self) -> None:
        """Перезапуск нужен после смены стратегии, списков или игрового фильтра."""
        was_active = self.status.is_active
        self.stop()
        if was_active:
            self.start()

    def shutdown(self) -> None:
        """Корректно гасит собственный процесс при закрытии приложения.

        Служба продолжает работать намеренно: её для того и ставят, чтобы обход
        жил без запущенного интерфейса.
        """
        self.stop_polling()
        self.telegram.stop()
        if self._profile_process is not None:
            self._profile_process.stop()
            self._profile_process = None
        if self._process is not None:
            self._process.stop()
            self._process = None

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)
