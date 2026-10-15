"""Чужая установка zapret на той же машине.

Имя службы у сборки Flowseal и у нас одно и то же — `zapret`, потому что это
её служба и есть. Поэтому у человека, который уже пользовался zapret вручную,
интерфейс при первом запуске показывает чужую установку как свою: «обход
работает, стратегия general (ALT)», хотя наша папка пуста, а стратегию с таким
именем негде взять.

Молча исправить это нельзя. Включение обхода пересоздаёт службу на наш путь, а
запуск в режиме процесса снимает все winws, включая чужие, — и прежняя
установка перестаёт работать, не спросив. Поэтому находим её и говорим прямо, а
решение оставляем человеку.

Опознаём по двум следам: путь к winws.exe в описании службы и пути запущенных
процессов. Всё, что лежит не в нашей папке ядра, принадлежит кому-то другому.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import psutil

from app.core import paths, service, winws

log = logging.getLogger(__name__)

# Путь к исполняемому файлу в описании службы: он может быть в кавычках, а
# дальше идут аргументы, среди которых встречаются и свои пробелы.
_EXE_RE = re.compile(r'^"?(.+?\.exe)"?(?:\s|$)', re.IGNORECASE)


@dataclass(frozen=True)
class ForeignInstall:
    """Найденная чужая сборка zapret."""

    root: Path
    winws: Path
    by_service: bool = False
    by_process: bool = False

    @property
    def label(self) -> str:
        return str(self.root)

    @property
    def source(self) -> str:
        if self.by_service and self.by_process:
            return "её служба управляет обходом, процесс запущен"
        if self.by_service:
            return "на неё настроена служба zapret"
        return "её winws сейчас запущен"


def executable_from_binpath(binpath: str) -> Path | None:
    """Выделяет путь к winws.exe из командной строки службы."""
    match = _EXE_RE.match(binpath.strip())
    if not match:
        return None
    try:
        return Path(match.group(1))
    except (OSError, ValueError):
        return None


def bundle_root(executable: Path) -> Path:
    """Корень сборки по пути к winws.exe.

    В сборке Flowseal файл лежит в `bin/`, поэтому корень — на уровень выше.
    Если раскладка другая, возвращаем папку самого файла: пусть путь будет
    приблизительным, но показать его человеку всё равно полезнее, чем ничего.
    """
    if executable.parent.name.lower() == "bin":
        return executable.parent.parent
    return executable.parent


def _is_ours(executable: Path) -> bool:
    try:
        return executable.resolve() == paths.winws_exe().resolve()
    except OSError:
        return str(executable).lower() == str(paths.winws_exe()).lower()


def detect() -> ForeignInstall | None:
    """Ищет установку zapret за пределами нашей папки."""
    foreign: dict[Path, dict[str, bool]] = {}

    if service.is_installed():
        executable = executable_from_binpath(service.installed_binpath())
        if executable is not None and not _is_ours(executable):
            foreign.setdefault(executable, {})["by_service"] = True

    # Перебираем процессы сами, а не через `winws.find_instances`: там
    # запрашиваются ещё и командные строки, а их psutil добывает чтением
    # чужой памяти. Для опроса раз в несколько секунд это дорого, и нам
    # здесь достаточно пути к файлу.
    for process in psutil.process_iter(["name", "exe"]):
        try:
            if (process.info["name"] or "").lower() != winws.PROCESS_NAME:
                continue
            path = process.info["exe"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if not path:
            continue
        executable = Path(path)
        if _is_ours(executable):
            continue
        foreign.setdefault(executable, {})["by_process"] = True

    if not foreign:
        return None

    # Если следов несколько, служба важнее: именно она переживает перезагрузку
    # и именно её перезапишет включение обхода.
    executable, marks = next(
        iter(sorted(foreign.items(), key=lambda item: not item[1].get("by_service", False)))
    )
    found = ForeignInstall(
        root=bundle_root(executable),
        winws=executable,
        by_service=marks.get("by_service", False),
        by_process=marks.get("by_process", False),
    )
    log.info("Найдена чужая установка zapret: %s (%s)", found.root, found.source)
    return found
