"""Отклик на повторный запуск: показать окно, когда об этом просит второй экземпляр.

Второй запуск программы не открывает своё окно, а подаёт сигнал первому
(`core/singleton.py`). Слушает его отдельный поток: ждать системное событие в
потоке интерфейса значило бы остановить интерфейс.

Показывает окно сам первый экземпляр, штатно, средствами Qt. Раньше второй
запуск показывал чужое окно снаружи через Windows API, и с окном, спрятанным в
трей, получалось хуже, чем ничего: Qt считал окно скрытым, не обрабатывал его, и
оно появлялось, но не отвечало на нажатия.
"""

from __future__ import annotations

import threading

from PyQt6.QtCore import QObject, pyqtSignal

from app.core import singleton

# Как часто поток просыпается проверить, не пора ли выходить. На отклик это не
# влияет: событие будит ожидание сразу, а таймаут нужен только для остановки.
POLL_MS = 500


class ActivationListener(QObject):
    """Превращает сигнал второго запуска в сигнал Qt."""

    activated = pyqtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        # Поток-демон: он ничего не держит и не должен задерживать выход.
        self._thread = threading.Thread(target=self._run, name="activation", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            if singleton.wait_activation(POLL_MS):
                # Из чужого для Qt потока сигнал уходит в очередь и выполняется
                # в потоке интерфейса — окно трогаем только оттуда.
                self.activated.emit()
