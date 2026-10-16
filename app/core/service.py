"""Управление службой Windows «zapret».

Повторяет то, что делает `service.bat`: создаёт службу с разобранной командной
строкой winws и запоминает имя стратегии в реестре. Эта запись в реестре —
единственный способ узнать, какая именно стратегия сейчас установлена, им же
пользуется и консольное меню апстрима.
"""

from __future__ import annotations

import logging
import subprocess
import winreg
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core import lists, paths
from app.core.batfile import StrategySpec, to_service_binpath

log = logging.getLogger(__name__)

SERVICE_NAME = "zapret"
WINDIVERT_SERVICE = "WinDivert"
DISPLAY_NAME = "zapret"
DESCRIPTION = "Zapret DPI bypass software"

# Имя значения в реестре, куда service.bat пишет имя выбранной стратегии.
STRATEGY_VALUE = "zapret-discord-youtube"
SERVICE_KEY = rf"System\CurrentControlSet\Services\{SERVICE_NAME}"

State = Literal["running", "stopped", "start_pending", "stop_pending", "not_installed", "unknown"]

LABELS: dict[State, str] = {
    "running": "работает",
    "stopped": "остановлена",
    "start_pending": "запускается",
    "stop_pending": "останавливается",
    "not_installed": "не установлена",
    "unknown": "состояние неизвестно",
}

_STATE_KEYWORDS: dict[str, State] = {
    "RUNNING": "running",
    "STOPPED": "stopped",
    "START_PENDING": "start_pending",
    "STOP_PENDING": "stop_pending",
}

_ENCODINGS = ("utf-8", "cp866", "cp1251")
CREATE_NO_WINDOW = 0x08000000

# Командная строка Windows ограничена 8191 символом, а стратегии разворачиваются
# в полсотни абсолютных путей и легко занимают пять тысяч. Если приложение лежит
# глубоко, запас кончится — лучше сказать об этом прямо, чем ловить обрезанную
# команду и необъяснимо неработающий обход.
MAX_COMMAND_LINE = 8000


class ServiceError(Exception):
    """Команда управления службой завершилась ошибкой."""


@dataclass(frozen=True)
class CommandResult:
    code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.code == 0


def _decode(raw: bytes) -> str:
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _run(args: list[str], timeout: int = 30) -> CommandResult:
    """Выполняет системную утилиту без всплывающего консольного окна."""
    try:
        completed = subprocess.run(  # noqa: S603 — фиксированный набор системных утилит
            args,
            capture_output=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ServiceError(f"не удалось выполнить {args[0]}: {error}") from error

    return CommandResult(completed.returncode, _decode(completed.stdout + completed.stderr))


def query_state(name: str = SERVICE_NAME) -> State:
    """Текущее состояние службы.

    Названия состояний sc.exe печатает по-английски даже на локализованной
    Windows, поэтому разбор по ключевым словам надёжен.
    """
    result = _run(["sc", "query", name])
    if not result.ok:
        return "not_installed"

    text = result.output.upper()
    for keyword, state in _STATE_KEYWORDS.items():
        if keyword in text:
            return state
    return "unknown"


def is_installed(name: str = SERVICE_NAME) -> bool:
    return query_state(name) != "not_installed"


def installed_strategy() -> str:
    """Имя стратегии, записанное в реестре при установке службы."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SERVICE_KEY) as key:
            value, _ = winreg.QueryValueEx(key, STRATEGY_VALUE)
            return str(value)
    except (FileNotFoundError, OSError):
        return ""


def _write_strategy_marker(name: str) -> None:
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_LOCAL_MACHINE, SERVICE_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, STRATEGY_VALUE, 0, winreg.REG_SZ, name)
    except OSError:
        log.warning("Не удалось записать имя стратегии в реестр")


def installed_binpath() -> str:
    """Командная строка, с которой зарегистрирована служба (для диагностики)."""
    result = _run(["sc", "qc", SERVICE_NAME, "8192"])
    if not result.ok:
        return ""
    for line in result.output.splitlines():
        if "BINARY_PATH_NAME" in line.upper():
            return line.split(":", 1)[1].strip() if ":" in line else ""
    return ""


def enable_tcp_timestamps() -> bool:
    """Включает TCP timestamps — без них не работает обход с `--dpi-desync-fooling=ts`."""
    result = _run(["netsh", "interface", "tcp", "set", "global", "timestamps=enabled"])
    return result.ok


def tcp_timestamps_enabled() -> bool:
    """Проверяет TCP timestamps, не завися от языка системы.

    Искать слово «timestamps» в выводе netsh нельзя: на русской Windows строка
    называется «Отметки времени RFC 1323», и поиск промахивается — параметр
    всегда выглядит выключенным, а кнопка починки кажется сломанной. Зато
    обозначение «RFC 1323» не переводится нигде, по нему и опознаём строку.
    """
    result = _run(["netsh", "interface", "tcp", "show", "global"])
    for line in result.output.splitlines():
        if "1323" not in line and "timestamp" not in line.lower():
            continue
        value = line.rpartition(":")[2].strip().lower()
        return value.startswith(("enabled", "включ"))

    # Запасной путь: имена свойств PowerShell не локализуются.
    fallback = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-NetTCPSetting -SettingName Internet).Timestamps",
        ]
    )
    return fallback.output.strip().lower().startswith("enabled")


def stop(name: str = SERVICE_NAME) -> None:
    state = query_state(name)
    if state in ("not_installed", "stopped"):
        return
    result = _run(["sc", "stop", name])
    if not result.ok and "1062" not in result.output:
        raise ServiceError(f"не удалось остановить службу: {result.output.strip()}")


def start(name: str = SERVICE_NAME) -> None:
    result = _run(["sc", "start", name])
    if not result.ok:
        raise ServiceError(f"не удалось запустить службу: {result.output.strip()}")


def remove(name: str = SERVICE_NAME) -> None:
    """Останавливает и удаляет службу. Отсутствие службы ошибкой не считается."""
    if query_state(name) == "not_installed":
        return
    stop(name)
    result = _run(["sc", "delete", name])
    if not result.ok and "1060" not in result.output:
        raise ServiceError(f"не удалось удалить службу: {result.output.strip()}")


def install(spec: StrategySpec, exe: Path | None = None, autostart: bool = True) -> None:
    """Пересоздаёт службу с командной строкой выбранной стратегии.

    Старая служба снимается: `sc create` не умеет менять уже существующую.
    """
    exe = exe or paths.winws_exe()
    if not exe.exists():
        raise ServiceError(f"не найден {exe}")
    if spec.is_empty:
        raise ServiceError(f"стратегия {spec.name} не содержит аргументов")

    # Та же причина, что и у обычного запуска: без пользовательских списков
    # winws не стартует, а служба падает молча — в окне видно только, что
    # она «запускается» и тут же останавливается.
    lists.ensure_user_lists()

    binpath = to_service_binpath(exe, spec.argv)
    if len(binpath) > MAX_COMMAND_LINE:
        raise ServiceError(
            f"командная строка стратегии «{spec.name}» заняла {len(binpath)} символов "
            f"при пределе {MAX_COMMAND_LINE}. Перенесите приложение в папку с более "
            "коротким путём, например в C:\\ZapretXmel."
        )

    remove()
    enable_tcp_timestamps()
    # sc.exe ждёт имя параметра и значение отдельными аргументами: "binPath=" "<...>".
    result = _run(
        [
            "sc",
            "create",
            SERVICE_NAME,
            "binPath=",
            binpath,
            "DisplayName=",
            DISPLAY_NAME,
            "start=",
            "auto" if autostart else "demand",
        ]
    )
    if not result.ok:
        raise ServiceError(f"не удалось создать службу: {result.output.strip()}")

    _run(["sc", "description", SERVICE_NAME, DESCRIPTION])
    _write_strategy_marker(spec.name)
    start()
    log.info("Служба установлена со стратегией %s", spec.name)


def windivert_state() -> State:
    """Состояние драйвера WinDivert — он поднимается вместе с winws."""
    return query_state(WINDIVERT_SERVICE)
