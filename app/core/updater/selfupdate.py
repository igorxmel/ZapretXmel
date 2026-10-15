"""Обновление самой программы.

Ядро zapret обновляется отдельно (`install.py`) — здесь речь про сам
ZapretXmel: чтобы человек не скачивал новую сборку руками каждый раз.

Запущенный .exe нельзя перезаписать, но в Windows его **можно переименовать**.
На этом и строится подмена: старый файл отодвигается в сторону, новый встаёт на
его место, программа перезапускается, а отодвинутый удаляется при следующем
старте. Вспомогательный процесс-«подменщик» при таком порядке не нужен — а
значит, нечему и сломаться на полпути.

Из исходников обновляться нечему: там это делает git. В таком режиме проверка
честно говорит, что обновлять нечего, вместо того чтобы молча ничего не делать.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from app import __version__
from app.core import process
from app.core.updater import github

log = logging.getLogger(__name__)

# Репозиторий самой программы. Отличается от апстрима Flowseal: там ядро,
# здесь интерфейс.
REPO = "igorxmel/ZapretXmel"

ASSET_NAME = "ZapretXmel.exe"
OLD_SUFFIX = ".old"
NEW_SUFFIX = ".new"

Progress = Callable[[str], None]


class SelfUpdateError(Exception):
    """Обновление программы не удалось."""


def is_frozen() -> bool:
    """Запущена ли собранная версия, а не исходники."""
    return bool(getattr(sys, "frozen", False))


def executable() -> Path:
    return Path(sys.executable).resolve()


def current_version() -> str:
    return __version__


def cleanup() -> None:
    """Убирает файл, отодвинутый прошлым обновлением.

    Вызывается при старте: пока программа работала, удалить его было нельзя.
    """
    if not is_frozen():
        return

    leftover = executable().with_suffix(OLD_SUFFIX + executable().suffix)
    if leftover.exists():
        try:
            leftover.unlink()
            log.info("Удалён файл прошлой версии: %s", leftover.name)
        except OSError:
            log.debug("Файл прошлой версии пока занят, удалю в следующий раз")


def check(repo: str = REPO, timeout: int = 20) -> github.Release | None:
    """Возвращает релиз, если он новее установленного."""
    release = github.latest_release(repo, timeout=timeout)
    return release if github.is_newer(release.version, current_version()) else None


def download(release: github.Release, progress: Progress | None = None) -> Path:
    """Скачивает новую сборку рядом с текущей."""
    asset = next((item for item in release.assets if item.name == ASSET_NAME), None)
    if asset is None:
        raise SelfUpdateError(f"в релизе {release.tag} нет файла {ASSET_NAME}")

    target = executable().with_suffix(NEW_SUFFIX + executable().suffix)
    if progress:
        progress(f"Скачиваю версию {release.version}…")

    github.download(asset, target)
    if target.stat().st_size < 1024:
        target.unlink(missing_ok=True)
        raise SelfUpdateError("скачанный файл подозрительно мал")

    return target


def apply(downloaded: Path, progress: Progress | None = None) -> None:
    """Ставит скачанную версию на место текущей.

    Порядок важен: сначала отодвигаем работающий файл, потом ставим новый.
    Если второй шаг не удастся, старый возвращается на место — программа
    останется рабочей.
    """
    if not is_frozen():
        raise SelfUpdateError("обновление доступно только в собранной версии")

    current = executable()
    backup = current.with_suffix(OLD_SUFFIX + current.suffix)

    if progress:
        progress("Заменяю файл программы…")

    backup.unlink(missing_ok=True)
    os.replace(current, backup)
    try:
        os.replace(downloaded, current)
    except OSError as error:
        os.replace(backup, current)
        raise SelfUpdateError(f"не удалось поставить новую версию: {error}") from error

    log.info("Программа обновлена, старый файл отодвинут в %s", backup.name)


def restart() -> None:
    """Запускает обновлённую программу и просит текущую закрыться.

    Окружение чистим обязательно: без этого новая версия подхватывает
    временную папку старой и не находит ни одного плагина Qt.
    """
    try:
        subprocess.Popen(  # noqa: S603 — собственный файл
            [str(executable())],
            close_fds=True,
            cwd=str(executable().parent),
            env=process.child_environment(),
        )
    except OSError as error:
        raise SelfUpdateError(f"не удалось перезапустить программу: {error}") from error


def update(release: github.Release, progress: Progress | None = None) -> None:
    """Скачивает и ставит новую версию. Перезапуск вызывается отдельно."""
    apply(download(release, progress), progress)
