"""Обновление самой программы.

Ядро zapret обновляется отдельно (`install.py`) — здесь речь про сам
ZapretXmel: чтобы человек не скачивал новую сборку руками каждый раз.

Запущенный .exe нельзя перезаписать, но в Windows его **можно переименовать**.
На этом и строится подмена: старый файл отодвигается в сторону, новый встаёт на
его место, программа перезапускается, а отодвинутый удаляется при следующем
старте. Вспомогательный процесс-«подменщик» при таком порядке не нужен — а
значит, нечему и сломаться на полпути.

Подмена — **только на выходе**, когда программа уже всё погасила. Переносная
сборка достаёт модули из своего exe по мере надобности и ищет его по имени. Пока
подмена шла сразу после скачивания, работающая версия при первом же новом импорте
читала байты из чужого файла и падала с «zlib.error: incorrect header check».
Скачанное лежит рядом как `.new.exe` и встаёт на место в `install_on_exit`.

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

# В имени файла — система: программу собирались переносить и на другие.
PORTABLE_NAME = "ZapretXmel-Windows-Portable.exe"
SETUP_NAME = "ZapretXmel-Windows-Setup.exe"
# Та же переносная под прежним именем. По нему ищут обновление версии до 0.4.0,
# и без него они так и остались бы на старой. Новые берут его, только если в
# релизе нет файла с новым именем.
ASSET_NAME = "ZapretXmel.exe"
OLD_SUFFIX = ".old"
NEW_SUFFIX = ".new"

Progress = Callable[[str], None]

# Версия, которая скачана и встанет на место при выходе. Не зная о ней, раздел
# «Обновления» предлагал ту же версию снова.
_staged = ""

# Скачанное — `.new.exe` рядом с программой или установщик, — с какими флагами
# запустить новую версию после выхода (None — не запускать) и отработала ли подмена.
_pending: Path | None = None
_relaunch: list[str] | None = None
_finished = False


class SelfUpdateError(Exception):
    """Обновление программы не удалось."""


def is_frozen() -> bool:
    """Запущена ли собранная версия, а не исходники."""
    return bool(getattr(sys, "frozen", False))


def executable() -> Path:
    return Path(sys.executable).resolve()


def current_version() -> str:
    return __version__


def asset_name(release: github.Release | None = None) -> str:
    """Какой файл релиза нужен этому варианту программы.

    С релизом — тот, что в нём действительно есть: у старых релизов переносная
    лежит только под прежним именем.
    """
    wanted = [SETUP_NAME] if paths.is_installed() else [PORTABLE_NAME, ASSET_NAME]
    if release is not None:
        present = {item.name for item in release.assets}
        for name in wanted:
            if name in present or name + ".sha256" in present:
                return name
    return wanted[0]


def staged_note(version: str) -> str:
    """Что будет со скачанной версией — для надписей и уведомлений."""
    return f"Версия {version} скачана и установится при перезапуске или закрытии программы"


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

    # Скачанное, но не вставшее на место: программу закрыли, не дав ей выйти как
    # следует. Ставить его сейчас нельзя — exe уже запущен, — а обновление
    # скачается заново.
    stale = executable().with_suffix(NEW_SUFFIX + executable().suffix)
    if stale.exists():
        try:
            stale.unlink()
            log.info("Удалено недоставленное обновление: %s", stale.name)
        except OSError:
            log.debug("Недоставленное обновление занято, удалю в следующий раз")


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
    name = asset_name(release)
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
    name = asset_name(release)
    return any(
        (item.name == name and item.digest) or item.name == name + ".sha256"
        for item in release.assets
    )


def _published_hash(release: github.Release) -> str:
    """Берёт SHA-256 из файла рядом со сборкой. Пусто — значит его нет."""
    hashes = asset_name(release) + ".sha256"
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
    """Запоминает скачанное. На место оно встанет при выходе (`install_on_exit`)."""
    global _pending, _finished

    if not is_frozen():
        raise SelfUpdateError("обновление доступно только в собранной версии")

    _pending = downloaded
    _finished = False
    log.info("Скачана новая версия, встанет при выходе: %s", downloaded.name)


def _swap(downloaded: Path) -> None:
    """Ставит скачанный exe на место текущего — только когда программа уже выходит.

    Порядок важен: сначала отодвигаем работающий файл, потом ставим новый.
    Если второй шаг не удастся, старый возвращается на место — программа
    останется рабочей.
    """
    current = executable()
    backup = current.with_suffix(OLD_SUFFIX + current.suffix)
    try:
        backup.unlink(missing_ok=True)
    except OSError as error:
        raise SelfUpdateError("файл прошлой версии ещё занят") from error
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

    Если скачано обновление, запуск откладывается до выхода: сначала новая версия
    встаёт на место (`install_on_exit`), потом запускается. Вызывающий после этого
    закрывает программу как обычно.
    """
    global _relaunch

    if _pending is not None:
        _relaunch = list(extra or [])
        return
    _launch(extra)


def _launch(extra: list[str] | None) -> None:
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
    command = [
        str(_pending),
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
    log.info(
        "Запущен установщик обновления%s", "" if relaunch is not None else " (без перезапуска)"
    )


def install_on_exit() -> None:
    """Ставит скачанное обновление, когда программа уже всё погасила и выходит.

    Позже вызывать нечего: после подмены exe переносная версия не может ничего
    импортировать. Если перед этим просили перезапуск (`restart`), новая версия
    запускается следом.
    """
    global _finished

    if _pending is None or _finished:
        return
    _finished = True
    try:
        if paths.is_installed():
            _run_setup(relaunch=_relaunch)
            return
        _swap(_pending)
        if _relaunch is not None:
            _launch(_relaunch)
    except SelfUpdateError as error:
        log.warning("Обновление при выходе не встало: %s", error)


def update(
    release: github.Release,
    progress: Progress | None = None,
    on_bytes: Callable[[int, int], None] | None = None,
) -> None:
    """Скачивает и ставит новую версию. Перезапуск вызывается отдельно."""
    global _staged
    apply(download(release, progress, on_bytes), progress)
    _staged = release.version
