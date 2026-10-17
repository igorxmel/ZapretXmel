"""Смена места установки.

Ядро zapret весит под сотню мегабайт, и держать его там, откуда запустили
.exe (а это чаще всего «Загрузки»), хочется не всем. Здесь — проверка
выбранной папки и перенос в неё уже установленного.

Переносится всё изменяемое состояние: ядро, настройки с логами и сайдкар
Telegram. Сам исполняемый файл остаётся на месте — он один и переживает
обновление себя через переименование, которому переезд только помешал бы.

Служба zapret хранит абсолютный путь к winws.exe, поэтому после переноса её
обязательно переустанавливают заново. За это отвечает вызывающая сторона —
`Controller.relocate`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app import logging_setup
from app.core import paths, process

log = logging.getLogger(__name__)

# Папки, которые составляют установку. Имена совпадают с теми, что отдаёт
# `paths`, — переносим их целиком, не разбирая содержимое.
MOVABLE: tuple[str, ...] = ("core", "data", "tgproxy")

# Список того, что не удалось убрать сразу: запущенный .exe на другом
# диске удалить нельзя, пока он работает.
CLEANUP_FILE = "cleanup.json"


@dataclass
class Relocation:
    """Итог переезда: что перенесли, а что уже лежало на новом месте."""

    target: Path
    moved: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    # Новый путь к программе, если она переехала следом за данными.
    executable: Path | None = None

    @property
    def summary(self) -> str:
        parts = []
        if self.moved:
            parts.append("перенесено: " + ", ".join(self.moved))
        if self.executable:
            parts.append("программа тоже переехала")
        if self.kept:
            parts.append("уже было на месте: " + ", ".join(self.kept))
        return "; ".join(parts) or "переносить было нечего"


def check_target(path: Path) -> str:
    """Причина, по которой папка не подходит. Пустая строка — подходит.

    Проверяется то, что сделает переезд невозможным или бессмысленным.
    Кириллица в пути и OneDrive не запрещены здесь: о них предупреждает
    диагностика, и запрещать выбор из-за предупреждения было бы грубо.
    """
    try:
        target = Path(path).expanduser()
    except (OSError, ValueError):
        return "Такой путь система не принимает."

    if not str(target).strip():
        return "Папка не выбрана."
    if not target.is_absolute():
        return "Нужен полный путь, например D:\\ZapretXmel."
    if not Path(target.anchor).exists():
        return f"Диска {target.anchor} нет в системе."
    if target.exists() and not target.is_dir():
        return "По этому пути лежит файл, а не папка."

    current = paths.install_root().resolve()
    try:
        resolved = target.resolve()
    except OSError:
        return "Такой путь система не принимает."

    if resolved == current:
        return "Это и есть текущее место установки."
    if resolved.is_relative_to(current) and _has_installed_parts(current):
        # Переносить дерево внутрь него самого нельзя технически, но сказать
        # об этом надо так, чтобы было понятно, что делать дальше: диалог
        # открывается в текущей папке, и выбрать что-то внутри неё — первое,
        # что приходит в голову.
        return (
            f"Эта папка лежит внутри текущей установки ({current}), "
            "а перенести её внутрь себя же нельзя. Выберите папку рядом "
            "или на другом диске."
        )
    if current.is_relative_to(resolved):
        return "Эта папка уже содержит установку — выберите другую."

    return _writable(resolved)


def _writable(target: Path) -> str:
    """Пробует создать папку и записать в неё: прав может не быть."""
    probe = target / ".zapretxmel-write-test"
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe.touch()
    except OSError:
        return "В эту папку нельзя записывать — выберите другую или запустите от администратора."
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            log.debug("Не удалось убрать пробный файл в %s", target)

    return ""


def _has_installed_parts(root: Path) -> bool:
    return any((root / name).exists() for name in MOVABLE)


FOLDER_NAME = "ZapretXmel"


def folder_for(chosen: Path) -> Path:
    """Куда на самом деле класть установку внутри выбранной папки.

    Человек выбирает «куда», думая о `D:\\Program`, а получает ядро, данные,
    прокси и .exe прямо в ней вперемешку с чужим добром. Поэтому в непустой
    папке заводим свою подпапку — и заодно пропадает соблазн выбрать место
    внутри текущей установки.

    Пустую папку и папку, которая уже наша, оставляем как есть: человек её
    для этого и создал, второй уровень вложенности там лишний.
    """
    try:
        if not chosen.exists():
            return chosen
        if _has_installed_parts(chosen):
            return chosen
        if not any(chosen.iterdir()):
            return chosen
    except OSError:
        return chosen

    return chosen / FOLDER_NAME


def free_space_mb(path: Path) -> int:
    """Свободное место на диске выбранной папки — чтобы показать его до переезда."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free // (1024 * 1024)
    except OSError:
        return 0


def installed_size_mb() -> int:
    """Размер того, что придётся перенести."""
    total = 0
    root = paths.install_root()
    for name in MOVABLE:
        folder = root / name
        if not folder.is_dir():
            continue
        for current, _, files in os.walk(folder):
            for file in files:
                try:
                    total += (Path(current) / file).stat().st_size
                except OSError:
                    continue
    return total // (1024 * 1024)


def relocate(target: Path) -> Relocation:
    """Переносит установку в `target` и запоминает новое место.

    Если в новой папке такая часть уже есть, она остаётся нетронутой, а старая
    не удаляется: молча перетирать чужое ядро или чужие настройки нельзя, а
    решать, какие из двух нужнее, — не дело программы.

    Указатель переписывается только после переноса. Иначе сбой на середине
    оставил бы программу смотреть в полупустую папку.
    """
    reason = check_target(target)
    if reason:
        raise ValueError(reason)

    source = paths.install_root().resolve()
    destination = Path(target).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    # Журнал пишется в переносимую папку, а Windows не даёт удалить открытый
    # файл: переезд на другой диск падал ровно на нём — копия уже лежала на
    # новом месте, а старая папка оставалась на прежнем.
    logging_setup.release_file()

    result = Relocation(target=destination)
    try:
        for name in MOVABLE:
            origin = source / name
            if not origin.exists():
                continue
            if (destination / name).exists():
                result.kept.append(name)
                continue
            _move_tree(origin, destination / name, destination)
            result.moved.append(name)

        # Указатель на старом месте больше не нужен ни в одном из случаев:
        # либо программа переедет следом и всё окажется рядом с ней, либо он
        # будет записан заново уже под новое место.
        paths.set_install_root(None)

        result.executable = _move_executable(destination)
        if result.executable is None:
            # Программа осталась на месте (так бывает при запуске из
            # исходников) — значит без указателя не обойтись.
            paths.set_install_root(None if destination == paths.app_root() else destination)
    finally:
        # Журнал поднимаем в любом случае, в том числе после сбоя: без него
        # не останется следов о том, где именно переезд оборвался.
        paths.reset_cache()
        paths.ensure_dirs()
        logging_setup.setup()

    for name in result.moved:
        log.info("Перенесено %s → %s", source / name, destination / name)
    if result.executable:
        log.info("Программа переехала в %s", result.executable)

    return result


def _move_tree(origin: Path, target: Path, destination: Path) -> None:
    """Переносит папку, переживая и другой диск, и занятые файлы.

    `shutil.move` между дисками копирует и удаляет оригинал, а удаление
    спотыкается на любом открытом файле — и тогда исключение прерывает
    переезд на середине. Здесь остаток не считается провалом: данные уже
    на новом месте, а то, что не удалось стереть, уберётся при следующем
    запуске.
    """
    try:
        os.replace(origin, target)
        return
    except OSError:
        log.info("Папка %s переезжает на другой диск — копирую", origin.name)

    shutil.copytree(origin, target, dirs_exist_ok=True)
    shutil.rmtree(origin, ignore_errors=True)

    if origin.exists():
        log.info("Папку %s сейчас удалить нельзя, уберём при следующем запуске", origin)
        schedule_cleanup(origin, data_dir=destination / "data")


def _move_executable(destination: Path) -> Path | None:
    """Переносит сам .exe следом за данными.

    Переносим, а не оставляем на месте: иначе в старой папке остаётся
    программа без данных, рядом с ней — указатель, и всё это выглядит как
    мусор, который человек должен убрать сам.

    Запущенный файл Windows разрешает переименовать, но не удалить. Поэтому
    в пределах диска он переезжает сразу, а на другой диск копируется, и
    старый экземпляр заносится в список на удаление: его снимут при
    следующем запуске, когда он уже никем не занят.
    """
    if not paths.is_frozen():
        return None

    current = paths.executable()
    moved = destination / current.name
    if moved == current:
        return None

    try:
        os.replace(current, moved)
        log.info("Программа переехала: %s → %s", current, moved)
        return moved
    except OSError:
        log.info("Переезд на другой диск — копирую %s", current.name)

    try:
        shutil.copy2(current, moved)
    except OSError as error:
        raise RuntimeError(f"не удалось перенести программу: {error}") from error

    schedule_cleanup(current, data_dir=destination / "data")
    return moved


def restart(executable: Path) -> None:
    """Запускает программу с нового места и просит текущую закрыться.

    Сам вызов только поднимает новый процесс: выйти текущему должен
    интерфейс, иначе окно закроется раньше, чем человек поймёт, что
    произошло.
    """
    try:
        subprocess.Popen(  # noqa: S603 — собственный файл
            [str(executable)],
            close_fds=True,
            cwd=str(executable.parent),
            env=process.child_environment(),
        )
    except OSError as error:
        raise RuntimeError(f"не удалось запустить программу из новой папки: {error}") from error


def schedule_cleanup(leftover: Path, data_dir: Path) -> None:
    """Запоминает файл, который нужно удалить при следующем запуске."""
    data_dir.mkdir(parents=True, exist_ok=True)
    note = data_dir / CLEANUP_FILE

    try:
        pending = set(json.loads(note.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pending = set()

    pending.add(str(leftover))
    try:
        note.write_text(json.dumps(sorted(pending), ensure_ascii=False), encoding="utf-8")
    except OSError:
        log.warning("Не удалось записать список на уборку")


def cleanup() -> int:
    """Удаляет то, что осталось от прошлого места. Вызывается при запуске."""
    note = paths.data_dir() / CLEANUP_FILE
    try:
        pending = json.loads(note.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0

    removed = 0
    survivors: list[str] = []
    for item in pending:
        leftover = Path(item)
        try:
            if leftover.is_dir():
                shutil.rmtree(leftover)
            else:
                leftover.unlink(missing_ok=True)
            removed += 1
            log.info("Убрано после переезда: %s", leftover)
        except OSError:
            # Файл ещё занят — попробуем в следующий раз.
            survivors.append(item)

    try:
        if survivors:
            note.write_text(json.dumps(survivors, ensure_ascii=False), encoding="utf-8")
        else:
            note.unlink(missing_ok=True)
    except OSError:
        log.debug("Не удалось обновить список на уборку")

    return removed
