"""Обновление самой программы.

Ядро zapret обновляется отдельно (`install.py`) — здесь речь про сам
ZapretXmel: чтобы человек не скачивал новую сборку руками каждый раз.

Запущенный .exe нельзя перезаписать, но в Windows его **можно переименовать**.
На этом и строится подмена: старый файл отодвигается в сторону, новый встаёт на
его место, программа перезапускается, а отодвинутый удаляется при следующем
старте. Вспомогательный процесс-«подменщик» при таком порядке не нужен — а
значит, нечему и сломаться на полпути.

Установленный вариант (сборка папкой) так не обновить: файлов в нём две сотни, и
подменять их по одному на ходу нельзя. Он скачивает установщик новой версии и
запускает его в тихом режиме. Установщик ждёт, пока программа закроется, ставит
новую поверх и, если его об этом попросили, запускает её.

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
from app.core import paths, process, singleton
from app.core.updater import github

log = logging.getLogger(__name__)

# Репозиторий самой программы. Отличается от апстрима Flowseal: там ядро,
# здесь интерфейс.
REPO = "igorxmel/ZapretXmel"

ASSET_NAME = "ZapretXmel.exe"
SETUP_NAME = "ZapretXmel-Setup.exe"
OLD_SUFFIX = ".old"
NEW_SUFFIX = ".new"

Progress = Callable[[str], None]

# Версия, которая уже стоит на месте файла программы и ждёт перезапуска.
# Работающий экземпляр к этому времени отодвинут в `.old` и занят. Не зная об
# этом, раздел «Обновления» предлагал ту же версию снова, вторая установка
# пыталась удалить `.old` — то есть саму себя — и падала с «Отказано в доступе».
_staged = ""

# Скачанный установщик новой версии и запущен ли он уже. Установленный вариант
# ставит обновление только после выхода — при перезапуске или при закрытии.
_setup: Path | None = None
_setup_started = False


class SelfUpdateError(Exception):
    """Обновление программы не удалось."""


def is_frozen() -> bool:
    """Запущена ли собранная версия, а не исходники."""
    return bool(getattr(sys, "frozen", False))


def executable() -> Path:
    return Path(sys.executable).resolve()


def current_version() -> str:
    return __version__


def asset_name() -> str:
    """Какой файл релиза нужен этому варианту программы."""
    return SETUP_NAME if paths.is_installed() else ASSET_NAME


def staged_note(version: str) -> str:
    """Что будет с поставленной версией — для надписей и уведомлений."""
    if paths.is_installed():
        return f"Версия {version} скачана и установится при перезапуске или закрытии программы"
    return f"Версия {version} установлена и запустится после перезапуска"


def staged_version() -> str:
    """Поставленная, но ещё не запущенная версия. Пусто — такой нет."""
    return _staged


def newest_here() -> str:
    """Самая новая версия на диске: поставленная, если есть, иначе запущенная."""
    return _staged or current_version()


def cleanup() -> None:
    """Убирает файл, отодвинутый прошлым обновлением.

    Вызывается при старте: пока программа работала, удалить его было нельзя.
    """
    if not is_frozen():
        return

    if paths.is_installed():
        # Установщик к этому времени отработал: новая версия уже запущена им.
        for setup in _setup_dir().glob("*.exe"):
            try:
                setup.unlink()
            except OSError:
                log.debug("Установщик %s пока занят, удалю в следующий раз", setup.name)
        return

    leftover = executable().with_suffix(OLD_SUFFIX + executable().suffix)
    if leftover.exists():
        try:
            leftover.unlink()
            log.info("Удалён файл прошлой версии: %s", leftover.name)
        except OSError:
            log.debug("Файл прошлой версии пока занят, удалю в следующий раз")


def check(
    repo: str = REPO, timeout: int = 20, testing: bool = False
) -> github.Release | None:
    """Возвращает релиз, если он новее установленного.

    `testing` включает тестовые сборки: они помечены на GitHub как
    pre-release и в обычный «последний релиз» не попадают.
    """
    release = github.latest_release(repo, timeout=timeout, testing=testing)
    return release if github.is_newer(release.version, newest_here()) else None


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
    name = asset_name()
    asset = next((item for item in release.assets if item.name == name), None)
    if asset is None:
        raise SelfUpdateError(f"в релизе {release.tag} нет файла {name}")

    if paths.is_installed():
        _setup_dir().mkdir(parents=True, exist_ok=True)
        target = _setup_dir() / SETUP_NAME
    else:
        target = executable().with_suffix(NEW_SUFFIX + executable().suffix)

    # Остаток от прошлой попытки убираем сам: иначе вторая загрузка писала
    # бы в занятый файл, а это ошибка доступа посреди обновления.
    _discard(target)

    if progress:
        progress(f"Скачиваю версию {release.version}{asset.size_note}…")

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


def _setup_dir() -> Path:
    """Куда класть установщик. Не рядом с программой: туда он сам и ставит."""
    return paths.data_dir() / "updates"


def _discard(path: Path) -> None:
    """Убирает файл, не поднимая шум, если он уже занят."""
    for leftover in (path, path.with_suffix(path.suffix + ".part")):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            log.debug("Файл %s занят, оставляю как есть", leftover.name)


def can_verify(release: github.Release) -> bool:
    """Есть ли с чем сверить скачанную сборку: хеш от GitHub или файл с хешем.

    Без них недокачанный файл встал бы на место рабочего незамеченным.
    """
    name = asset_name()
    return any(
        (item.name == name and item.digest) or item.name == name + ".sha256"
        for item in release.assets
    )


def _published_hash(release: github.Release) -> str:
    """Берёт SHA-256 из файла рядом со сборкой. Пусто — значит его нет."""
    hashes = asset_name() + ".sha256"
    asset = next((item for item in release.assets if item.name == hashes), None)
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
    global _setup

    if not is_frozen():
        raise SelfUpdateError("обновление доступно только в собранной версии")

    if paths.is_installed():
        # Ставить нечего: установщик сделает это сам, когда программа закроется.
        _setup = downloaded
        log.info("Скачан установщик новой версии: %s", downloaded)
        return

    current = executable()
    backup = current.with_suffix(OLD_SUFFIX + current.suffix)

    if progress:
        progress("Заменяю файл программы…")

    if _staged:
        # В `.old` лежит работающая программа, её не трогаем. На месте файла —
        # прошлое обновление, оно не запущено, и его можно просто заменить.
        try:
            os.replace(downloaded, current)
        except OSError as error:
            raise SelfUpdateError(f"не удалось поставить новую версию: {error}") from error
        log.info("Программа обновлена поверх ещё не запущенной версии %s", _staged)
        return

    try:
        backup.unlink(missing_ok=True)
    except OSError as error:
        raise SelfUpdateError(
            "файл прошлой версии ещё занят. Перезапустите программу и попробуйте снова"
        ) from error
    os.replace(current, backup)
    try:
        os.replace(downloaded, current)
    except OSError as error:
        os.replace(backup, current)
        raise SelfUpdateError(f"не удалось поставить новую версию: {error}") from error

    log.info("Программа обновлена, старый файл отодвинут в %s", backup.name)


def restart(extra: list[str] | None = None) -> None:
    """Запускает обновлённую программу и просит текущую закрыться.

    Окружение чистим обязательно: без этого новая версия подхватывает
    временную папку старой и не находит ни одного плагина Qt. `extra` —
    флаги для нового экземпляра: остаться в трее, поднять обход и прокси.
    """
    if paths.is_installed():
        if _setup is None:
            raise SelfUpdateError("установщик новой версии не скачан")
        _run_setup(relaunch=extra or [])
        return

    try:
        subprocess.Popen(  # noqa: S603 — собственный файл
            [str(executable()), singleton.RESTART_FLAG, *(extra or [])],
            close_fds=True,
            cwd=str(executable().parent),
            env=process.child_environment(),
        )
    except OSError as error:
        raise SelfUpdateError(f"не удалось перезапустить программу: {error}") from error


def _run_setup(relaunch: list[str] | None) -> None:
    """Запускает скачанный установщик в тихом режиме.

    `relaunch` — с какими флагами установщику запустить новую версию; `None` —
    не запускать: обновление ставится при закрытии программы, и открывать её
    снова никто не просил.
    """
    global _setup_started

    command = [
        str(_setup),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        f"/LOG={paths.logs_dir() / 'setup.log'}",
    ]
    if relaunch is not None:
        command.append("/LAUNCH=1")
        if relaunch:
            command.append("/LAUNCHARGS=" + " ".join(relaunch))

    try:
        subprocess.Popen(  # noqa: S603 — установщик из нашего же релиза, хеш сверен
            command,
            close_fds=True,
            cwd=str(_setup_dir()),
            env=process.child_environment(),
        )
    except OSError as error:
        raise SelfUpdateError(f"не удалось запустить установщик: {error}") from error
    _setup_started = True
    log.info(
        "Запущен установщик обновления%s", "" if relaunch is not None else " (без перезапуска)"
    )


def install_on_exit() -> None:
    """Ставит скачанное обновление, когда программу закрывают.

    Иначе у установленного варианта обновление ждало бы перезапуска, о котором
    человек не знает: закрыл программу, открыл — а версия прежняя.
    """
    if not paths.is_installed() or _setup is None or _setup_started:
        return
    try:
        _run_setup(relaunch=None)
    except SelfUpdateError as error:
        log.warning("Обновление при закрытии не запустилось: %s", error)


def update(
    release: github.Release,
    progress: Progress | None = None,
    on_bytes: Callable[[int, int], None] | None = None,
) -> None:
    """Скачивает и ставит новую версию. Перезапуск вызывается отдельно."""
    global _staged
    apply(download(release, progress, on_bytes), progress)
    _staged = release.version
