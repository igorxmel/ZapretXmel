"""Кнопка «Почини»: проверить, быстро попробовать лучшее, при нужде перебрать всё.

Один объект на всю программу: кнопка есть и на обзоре, и в мини-окне, а запускать два перебора
одновременно нельзя. Он живёт в контроллере, экраны только показывают его ход.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from app.core import repair, strategies
from app.core.probe import services
from app.core.probe.autopick import Report, save_report
from app.ui.theme.tokens import COLORS
from app.ui.workers import AutoPickWorker, QuickCheckWorker

log = logging.getLogger(__name__)

# winws нужно мгновение, прежде чем он начнёт перехватывать пакеты.
SETTLE_MS = 1500


class RepairFlow(QObject):
    """Весь путь от нажатия до ответа."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(str, str)
    running_changed = pyqtSignal(bool)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.running = False
        self._was_active = False
        self._previous = ""
        self._specs: list = []
        self._tried: list[str] = []
        self._full_pass = False
        self._quick: QuickCheckWorker | None = None
        self._picker: AutoPickWorker | None = None

    # --- начало и конец --------------------------------------------------

    def refusal(self) -> str:
        """Почему начать нельзя. Пусто — можно."""
        status = self.controller.status
        if self.running:
            return "Починка уже идёт"
        if self.controller.picking:
            return "Идёт подбор стратегии, дождитесь его конца"
        if not status.core_present:
            return "Сначала установите ядро zapret"
        if status.active_vpn:
            return f"Выключите {status.active_vpn}: пока он работает, проверка измеряет его"
        return ""

    def start(self) -> None:
        reason = self.refusal()
        if reason:
            self.finished.emit(reason, COLORS["warning"])
            return

        self._set_running(True)
        status = self.controller.status
        self._was_active = status.is_active
        self._previous = status.active_strategy or self.controller.settings.selected_strategy
        self._specs = strategies.load_all()
        self._tried = []
        self._full_pass = False

        self.progress.emit("Проверяю, что не работает…")
        self._run_quick(self._first_check_done)

    def cancel(self) -> None:
        if self._picker is not None and self._picker.isRunning():
            self._picker.cancel()

    def _set_running(self, running: bool) -> None:
        self.running = running
        self.running_changed.emit(running)

    def _finish(self, text: str, colour: str) -> None:
        self._set_running(False)
        self.finished.emit(text, colour)

    def _fail(self, message: str) -> None:
        log.warning("Починка прервалась: %s", message)
        self._restore()
        self._finish(f"Не получилось: {message}", COLORS["danger"])

    def _restore(self) -> None:
        """Возвращает как было: человек нажимал «почини», а не «выключи»."""
        if not self._was_active or self.controller.status.is_active:
            return
        if self._previous:
            self.controller.select_strategy(self._previous)
        self.controller.start()

    # --- шаги ------------------------------------------------------------

    def _run_quick(self, done) -> None:
        settings = self.controller.settings
        self._quick = QuickCheckWorker(
            timeout=settings.probe_timeout, parallel=settings.probe_parallel
        )
        self._quick.done.connect(done)
        self._quick.failed.connect(self._fail)
        self._quick.start()

    def _first_check_done(self, check) -> None:
        self.controller.remember_check(check)
        if check.everything_works and self.controller.status.is_active:
            self._finish("Всё уже работает, чинить нечего.", COLORS["success"])
            return

        names = [spec.name for spec in self._specs]
        favorites = list(self.controller.settings.favorites)
        short = repair.shortlist(names, favorites, self._previous)
        if not short:
            self._full_pass = True
            short = names
        if not short:
            self._finish("Нет ни одной стратегии.", COLORS["danger"])
            return

        self.controller.stop()
        self._pick(short)

    def _pick(self, names: list[str]) -> None:
        wanted = [spec for spec in self._specs if spec.name in names]
        self._tried.extend(names)
        self.progress.emit(
            "Перебираю все стратегии, это займёт несколько минут…"
            if self._full_pass
            else f"Пробую лучшие стратегии: {len(wanted)}…"
        )
        settings = self.controller.settings
        self._picker = AutoPickWorker(
            wanted,
            mode="services",
            chosen=services.discover(),
            timeout=settings.probe_timeout,
            parallel=settings.probe_parallel,
        )
        self._picker.progress.connect(self.progress)
        self._picker.done.connect(self._pick_done)
        self._picker.failed.connect(self._fail)
        self._picker.start()

    def _pick_done(self, report: Report) -> None:
        try:
            save_report(report)
        except OSError:
            log.info("Отчёт починки не сохранён", exc_info=True)

        if report.cancelled:
            self._restore()
            self._finish("Починка остановлена, вернул как было.", COLORS["text_muted"])
            return

        if repair.nothing_is_blocked(report):
            self._restore()
            self._finish(
                "Сейчас всё открывается и без обхода, менять стратегию незачем.",
                COLORS["success"],
            )
            return

        best = repair.choose(report)
        if repair.fully_works(best):
            self._apply(best.name)
            return

        rest = repair.remaining([spec.name for spec in self._specs], self._tried)
        if rest and not self._full_pass:
            self._full_pass = True
            self._pick(rest)
            return

        if best is not None:
            self._apply(best.name)
            return

        self._restore()
        self._finish(
            "Ни одна стратегия не помогла. Откройте «Диагностику»: возможно, дело не в них.",
            COLORS["danger"],
        )

    def _apply(self, name: str) -> None:
        self.progress.emit(f"Включаю «{name}» и проверяю…")
        self.controller.select_strategy(name)
        self.controller.start()
        verify = lambda check: self._verified(name, check)  # noqa: E731
        QTimer.singleShot(SETTLE_MS, lambda: self._run_quick(verify))

    def _verified(self, name: str, check) -> None:
        self.controller.remember_check(check)
        if check.everything_works:
            self._finish(f"Готово: включена «{name}», всё работает.", COLORS["success"])
        elif check.working:
            listed = ", ".join(check.broken)
            self._finish(f"Включена «{name}», но не работает: {listed}.", COLORS["warning"])
        else:
            self._finish(
                f"Включена «{name}», но проверка ничего не открыла. Проверьте интернет.",
                COLORS["danger"],
            )
