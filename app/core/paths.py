"""Пути приложения.

По умолчанию всё хранится рядом с исполняемым файлом (портативный режим):
управляемая копия ядра zapret, настройки, логи, бэкапы и история прогонов.
Так папку можно перенести на другую машину целиком.

Место установки разрешено сменить — ядро весит под сотню мегабайт, и держать
его на системном диске или в «Загрузках» хочется далеко не всем. Выбранный
путь лежит в `location.txt` рядом с исполняемым файлом, а не в настройках:
сами настройки живут внутри выбранной папки, и указатель на неё не может
храниться там же. Нет файла — портативный режим, как и раньше.
"""

from __future__ import annotations

import sys
from functools import cache
from pathlib import Path


@cache
def app_root() -> Path:
    """Корень приложения.

    В сборке PyInstaller это папка с .exe, в исходниках — корень репозитория.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


@cache
def assets_dir() -> Path:
    """Картинки приложения.

    В сборке PyInstaller ресурсы распаковываются во временную папку `_MEIPASS`,
    а не лежат рядом с .exe — поэтому путь ищется в обоих местах.
    """
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", "")) / "assets"
        if bundled.is_dir():
            return bundled
    return app_root() / "assets"


def logo_file() -> Path:
    return assets_dir() / "logo.png"


def banner_file() -> Path:
    """Логотип с надписью — для шапки и приветствия."""
    return assets_dir() / "banner.png"


def icon_file() -> Path:
    return assets_dir() / "logo.ico"


def location_file() -> Path:
    """Указатель на место установки. Лежит рядом с программой."""
    return app_root() / "location.txt"


@cache
def install_root() -> Path:
    """Папка, в которую ставится ядро и всё изменяемое состояние.

    Если указатель испорчен или ведёт на исчезнувший диск (путь был на
    флешке), возвращаемся к портативному режиму: лучше поставить ядро заново
    рядом с программой, чем падать при каждом обращении к файлам.
    """
    try:
        raw = location_file().read_text(encoding="utf-8").strip()
    except OSError:
        return app_root()

    if not raw:
        return app_root()

    try:
        chosen = Path(raw).expanduser()
        if not chosen.is_absolute() or not Path(chosen.anchor).exists():
            return app_root()
    except (OSError, ValueError):
        return app_root()

    return chosen


def is_portable() -> bool:
    """Правда, если место установки не выбирали и всё лежит рядом с программой."""
    return install_root() == app_root()


def set_install_root(path: Path | None) -> None:
    """Запоминает место установки. `None` возвращает портативный режим.

    Файлы не переносит — этим занимается `app.core.install`.
    """
    pointer = location_file()
    if path is None:
        pointer.unlink(missing_ok=True)
    else:
        target = Path(path).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        pointer.write_text(str(target), encoding="utf-8")

    reset_cache()


def reset_cache() -> None:
    """Сбрасывает кэш путей после смены места установки."""
    install_root.cache_clear()
    core_dir.cache_clear()
    data_dir.cache_clear()


@cache
def core_dir() -> Path:
    """Управляемая копия сборки zapret (bin/, lists/, general*.bat, service.bat)."""
    return install_root() / "core"


@cache
def data_dir() -> Path:
    return install_root() / "data"


def config_file() -> Path:
    return data_dir() / "config.json"


def logs_dir() -> Path:
    return data_dir() / "logs"


def backups_dir() -> Path:
    """Бэкапы ядра для отката обновления."""
    return data_dir() / "backups"


def history_dir() -> Path:
    """История прогонов авто-подбора стратегий."""
    return data_dir() / "history"


def downloads_dir() -> Path:
    """Временные загрузки апдейтера."""
    return data_dir() / "downloads"


def upstream_dir() -> Path:
    """Отпечатки апстрима и отчёты о расхождениях."""
    return app_root() / "upstream"


# --- производные пути внутри ядра ---------------------------------------


def core_bin() -> Path:
    return core_dir() / "bin"


def core_lists() -> Path:
    return core_dir() / "lists"


def core_utils() -> Path:
    return core_dir() / "utils"


def winws_exe() -> Path:
    return core_bin() / "winws.exe"


def ensure_dirs() -> None:
    """Создаёт каталоги приложения. Ядро не трогаем — им занимается апдейтер."""
    for path in (data_dir(), logs_dir(), backups_dir(), history_dir(), downloads_dir()):
        path.mkdir(parents=True, exist_ok=True)
