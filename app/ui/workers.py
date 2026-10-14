"""Фоновые задачи.

Весь код из `app.core` синхронный и ничего не знает о Qt — поэтому любая
операция, которая ходит в сеть, дёргает `sc` или перебирает стратегии, уходит
в поток, а результат возвращается сигналом. Так окно не замирает на минуты
во время прогона.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.batfile import StrategySpec
from app.core.probe.autopick import AutoPicker, Mode, Report, StrategyScore
from app.core.probe.dpi import DpiTarget
from app.core.probe.services import Service
from app.core.updater import github, install

log = logging.getLogger(__name__)


class Task(QThread):
    """Выполняет произвольную функцию в фоне и отдаёт её результат."""

    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, func: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            self.done.emit(self._func(*self._args, **self._kwargs))
        except Exception as error:  # noqa: BLE001 — любая ошибка должна дойти до интерфейса
            log.exception("Фоновая задача завершилась ошибкой")
            self.failed.emit(str(error))


class AutoPickWorker(QThread):
    """Перебор стратегий с отчётом о ходе работы."""

    progress = pyqtSignal(str)
    strategy_done = pyqtSignal(object)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        specs: list[StrategySpec],
        mode: Mode = "services",
        chosen: list[Service] | None = None,
        dpi_targets: list[DpiTarget] | None = None,
        timeout: int = 6,
        parallel: int = 8,
    ):
        super().__init__()
        self._specs = specs
        self._chosen = chosen or []
        self._dpi_targets = dpi_targets or []
        self._picker = AutoPicker(mode=mode, timeout=timeout, parallel=parallel)

    def cancel(self) -> None:
        self._picker.stop()
        self.progress.emit("Останавливаю прогон…")

    def run(self) -> None:
        try:
            report: Report = self._picker.run(
                self._specs,
                chosen=self._chosen,
                dpi_targets=self._dpi_targets,
                on_progress=self.progress.emit,
                on_strategy_done=self._emit_score,
            )
            self.done.emit(report)
        except Exception as error:  # noqa: BLE001 — показать причину, а не молча упасть
            log.exception("Прогон стратегий сорвался")
            self.failed.emit(str(error))

    def _emit_score(self, score: StrategyScore) -> None:
        self.strategy_done.emit(score)


class CoreUpdateWorker(QThread):
    """Скачивание и установка релиза ядра."""

    progress = pyqtSignal(str)
    percent = pyqtSignal(int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, release: github.Release, destination: Path):
        super().__init__()
        self._release = release
        self._destination = destination

    def run(self) -> None:
        try:
            asset = self._release.zip_asset()
            if asset is None:
                raise install.InstallError(
                    f"в релизе {self._release.tag} нет архива сборки"
                )

            self.progress.emit(f"Скачиваю {asset.name}…")
            archive = self._destination / asset.name
            github.download(asset, archive, progress=self._on_download)

            self.progress.emit("Проверяю и устанавливаю…")
            version = install.install_core(archive, progress=self.progress.emit)

            archive.unlink(missing_ok=True)
            self.done.emit(version)
        except Exception as error:  # noqa: BLE001 — обновление не должно ронять приложение
            log.exception("Обновление ядра не удалось")
            self.failed.emit(str(error))

    def _on_download(self, downloaded: int, total: int) -> None:
        if total > 0:
            self.percent.emit(int(downloaded * 100 / total))
