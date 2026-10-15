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


def download(
    release: github.Release,
    progress: Progress | None = None,
    on_bytes: Callable[[int, int], None] | None = None,
) -> Path:
    """Скачивает новую сборку рядом с текущей и проверяет, что она целая.

    Целость проверяется по файлу с хешем из того же релиза. Полсотни
    мегабайт по дороге могут оборваться, а недокачанную программу мы
    поставим на место рабочей — и она не запустится вовсе.
    """
    asset = next((item for item in release.assets if item.name == ASSET_NAME), None)
    if asset is None:
        raise SelfUpdateError(f"в релизе {release.tag} нет файла {ASSET_NAME}")

    target = executable().with_suffix(NEW_SUFFIX + executable().suffix)

    # Остаток от прошлой попытки убираем сам: иначе вторая загрузка писала
    # бы в занятый файл, а это ошибка доступа посреди обновления.
    _discard(target)

    if progress:
        progress(f"Скачиваю версию {release.version} ({asset.size // 1048576} МБ)…")

    try:
        digest = github.download(asset, target, progress=on_bytes)
    except Exception as error:
        _discard(target)
        raise SelfUpdateError(
            f"не удалось скачать обновление: {error}. "
            "Файл берётся с GitHub — если обход сейчас выключен, включите его."
        ) from error

    if target.stat().st_size < 1024:
        _discard(target)
        raise SelfUpdateError("скачанный файл подозрительно мал")

    expected = _published_hash(release)
    if expected and digest.lower() != expected.lower():
        _discard(target)
        raise SelfUpdateError(
            "скачанный файл не совпал с published-хешем — загрузка оборвалась. "
            "Попробуйте ещё раз."
        )

    return target


def _discard(path: Path) -> None:
    """Убирает файл, не поднимая шум, если он уже занят."""
    for leftover in (path, path.with_suffix(path.suffix + ".part")):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            log.debug("Файл %s занят, оставляю как есть", leftover.name)


def _published_hash(release: github.Release) -> str:
    """Берёт SHA-256 из файла рядом со сборкой. Пусто — значит его нет."""
    asset = next((item for item in release.assets if item.name == ASSET_NAME + ".sha256"), None)
    if asset is None:
        return ""

    try:
        text = github.fetch_text(asset)
    except Exception:  # noqa: BLE001 — без хеша просто не проверяем
        log.warning("Не удалось прочитать файл с хешем, пропускаю проверку")
        return ""

    return text.split()[0] if text.split() else ""


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


def update(
    release: github.Release,
    progress: Progress | None = None,
    on_bytes: Callable[[int, int], None] | None = None,
) -> None:
    """Скачивает и ставит новую версию. Перезапуск вызывается отдельно."""
    apply(download(release, progress, on_bytes), progress)
