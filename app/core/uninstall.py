"""Удаление того, что программа принесла на компьютер.

Установщика у неё нет, и убрать её из «Программ и компонентов» нельзя —
значит, убирать за собой она должна сама. Иначе после «удаления» (то есть
стирания .exe) в системе остаются служба Windows, драйвер, сотня мегабайт
ядра и папка с настройками, о которых человек не знает.

Три отдельные операции, потому что и поводов три: освободить место, убрать
прокси, уйти совсем.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app import logging_setup
from app.core import paths, service, shortcut, telegram, winws

log = logging.getLogger(__name__)


@dataclass
class Removed:
    """Что удалось убрать, а что осталось."""

    gone: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    needs_reboot: bool = False

    @property
    def summary(self) -> str:
        parts = []
        if self.gone:
            parts.append("удалено: " + ", ".join(self.gone))
        if self.kept:
            parts.append("осталось: " + ", ".join(self.kept))
        if self.needs_reboot:
            # Говорим прямо, а не «произошла ошибка»: человек видит папку на
            # диске и должен понимать, почему она там и что с этим делать.
            parts.append(
                "драйвер WinDivert выгрузится только после перезагрузки — "
                "остаток папки удалится вместе с ним"
            )
        return "; ".join(parts) or "удалять было нечего"


def _drop(path: Path, title: str, result: Removed) -> None:
    """Удаляет файл или папку, не останавливаясь на том, что занято.

    Остановиться на первой же ошибке нельзя: `shutil.rmtree` обходит папку
    сверху вниз и бросает исключение на первом запертом файле, оставляя
    остальное нетронутым. На удалении ядра это было особенно плохо — папка
    `bin` идёт первой, драйвер `WinDivert.dll` стирался, а лежащий следом
    `winws.exe` оставался: ядро выглядело установленным, служба создавалась
    и падала с «служба не ответила своевременно».
    """
    if not path.exists():
        return

    locked: list[Path] = []

    def remember(_function, failed, _error) -> None:
        locked.append(Path(failed))

    if path.is_dir():
        shutil.rmtree(path, onexc=remember)
    else:
        try:
            path.unlink()
        except OSError as error:
            locked.append(path)
            log.warning("Не удалось удалить %s: %s", path, error)

    if path.exists() or locked:
        result.kept.append(title)
        for item in locked[:5]:
            log.warning("Занято, осталось на диске: %s", item)
    else:
        result.gone.append(title)
        log.info("Удалено: %s", path)


def remove_core() -> Removed:
    """Убирает ядро zapret: службу, процессы и саму папку.

    Служба и процессы — в первую очередь: пока winws жив, файлы ядра заняты,
    и папка не удалится.
    """
    result = Removed()

    if service.is_installed():
        service.remove()
        result.gone.append("служба Windows")

    if winws.kill_all():
        result.gone.append("процессы winws")

    # Драйвер надо выгрузить до файлов: пока он в ядре, Windows держит
    # открытым WinDivert64.sys, и папка ядра не удаляется целиком.
    if not service.unload_windivert():
        result.needs_reboot = True

    _drop(paths.core_dir(), "папка ядра", result)
    _drop(paths.backups_dir(), "бэкапы ядра", result)
    return result


def remove_proxy() -> Removed:
    """Убирает прокси для Telegram вместе с его настройками.

    В самом Telegram прокси останется прописанным — его настройки не наши,
    и лезть в них мы не будем. Человеку придётся убрать его там самому.
    """
    result = Removed()

    proxy = telegram.TelegramProxy()
    if proxy.is_running():
        proxy.stop()
        result.gone.append("запущенный прокси")

    _drop(telegram.home(), "папка прокси", result)
    return result


def remove_everything() -> Removed:
    """Убирает всё: ядро, прокси, настройки, журналы и ярлык.

    Сам .exe остаётся — удалить работающий файл Windows не даст. Его человек
    стирает сам, и это честнее, чем самоуничтожение по таймеру: программа,
    которая стирает файлы после выхода, выглядит ровно как то, от чего
    антивирусы и защищают.
    """
    result = remove_core()
    result.gone.extend(remove_proxy().gone)

    if shortcut.exists():
        shortcut.remove()
        result.gone.append("ярлык")

    # Журнал лежит внутри удаляемой папки, а открытый файл Windows удалить
    # не даёт — та же беда, на которой спотыкался переезд. Записывать после
    # этого уже некуда, поэтому отпускаем в последний момент.
    logging_setup.release_file()

    _drop(paths.data_dir(), "настройки и журналы", result)
    _drop(paths.location_file(), "указатель на папку", result)
    return result


def leftovers() -> list[str]:
    """Что останется после удаления всего — чтобы сказать об этом заранее."""
    remaining = [f"сам файл программы ({paths.executable().name})"]
    if telegram.is_installed():
        remaining.append("прокси, прописанный в настройках Telegram")
    return remaining
