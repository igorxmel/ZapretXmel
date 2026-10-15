"""Сбор фактов о системе.

Здесь только факты — никаких выводов: истолкованием занимается `rules.py`.
Такое разделение нужно, чтобы те же данные можно было отдать слою ИИ и выгрузить
в диагностический пакет, не таская за собой логику интерфейса.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import winreg
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from app.core import coreinfo, gamefilter, ipset, lists, paths, service, strategies, winws

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
_ENCODINGS = ("utf-8", "cp866", "cp1251")
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")

INTERNET_SETTINGS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

@dataclass(frozen=True)
class ServiceSignature:
    """Признак конфликтующей службы.

    `all_of` — все слова должны встретиться в одном имени (служб со словом
    «Intel» на обычной машине много, и помечать их все как конфликт неверно).
    `any_of` — достаточно любого совпадения.
    """

    label: str
    hint: str
    all_of: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()

    def matches(self, lowered_names: list[str]) -> bool:
        if self.all_of and any(
            all(needle in name for needle in self.all_of) for name in lowered_names
        ):
            return True
        return bool(self.any_of) and any(
            needle in name for name in lowered_names for needle in self.any_of
        )


# Службы, которые, по опыту апстрима, конфликтуют с обходом.
CONFLICTING_SERVICES: tuple[ServiceSignature, ...] = (
    ServiceSignature(
        label="Killer",
        hint="Сетевой менеджер Killer перехватывает трафик раньше WinDivert.",
        any_of=("killer",),
    ),
    ServiceSignature(
        label="Intel Connectivity Network Service",
        hint="Служба Intel конфликтует с перехватом пакетов.",
        all_of=("intel", "connectivity", "network"),
    ),
    ServiceSignature(
        label="Check Point",
        hint="Клиент Check Point несовместим с обходом, его придётся удалить.",
        any_of=("tracsrvwrapper", "epwd"),
    ),
    ServiceSignature(
        label="SmartByte",
        hint="SmartByte управляет приоритетами трафика и ломает обход.",
        any_of=("smartbyte",),
    ),
)

CONFLICTING_PROCESSES: dict[str, str] = {
    "AdguardSvc.exe": "Adguard",
    "goodbyedpi.exe": "GoodbyeDPI",
    "byedpi.exe": "ByeDPI",
    "ciadpi.exe": "ByeDPI (ciadpi)",
    "spoofdpi.exe": "SpoofDPI",
}


@dataclass
class ProxyInfo:
    enabled: bool = False
    server: str = ""


@dataclass
class SystemFacts:
    """Снимок состояния системы и установки zapret."""

    # Система
    os_version: str = ""
    is_admin: bool = False
    bfe_running: bool = False
    tcp_timestamps: bool = False
    proxy: ProxyInfo = field(default_factory=ProxyInfo)
    conflicting_services: list[str] = field(default_factory=list)
    conflicting_processes: list[str] = field(default_factory=list)
    vpn_services: list[str] = field(default_factory=list)
    active_vpn: str = ""

    # Установка
    core_present: bool = False
    core_version: str = ""
    core_path: str = ""
    strategy_count: int = 0
    available_strategies: list[str] = field(default_factory=list)
    windivert_driver_present: bool = False
    path_has_cyrillic: bool = False
    path_in_onedrive: bool = False

    # Состояние обхода
    service_state: str = "not_installed"
    service_strategy: str = ""
    windivert_state: str = "not_installed"
    winws_count: int = 0
    winws_cmdlines: list[str] = field(default_factory=list)

    # Настройки сборки
    ipset_mode: str = "any"
    ipset_has_backup: bool = False
    game_filter: str = "disabled"
    user_list_counts: dict[str, int] = field(default_factory=dict)


def _decode(raw: bytes) -> str:
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _run(args: list[str], timeout: int = 30) -> str:
    try:
        completed = subprocess.run(  # noqa: S603 — фиксированный набор системных утилит
            args,
            capture_output=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return _decode(completed.stdout + completed.stderr)


def all_service_names() -> list[str]:
    """Имена всех служб системы — один вызов sc вместо десятка."""
    output = _run(["sc", "query", "type=", "service", "state=", "all"])
    return [
        line.split(":", 1)[1].strip()
        for line in output.splitlines()
        if line.upper().startswith("SERVICE_NAME")
    ]


def find_conflicting_services(names: list[str]) -> list[str]:
    """Названия найденных конфликтующих служб."""
    lowered = [name.lower() for name in names]
    return [
        signature.label for signature in CONFLICTING_SERVICES if signature.matches(lowered)
    ]


def find_vpn_services(names: list[str]) -> list[str]:
    return [name for name in names if "vpn" in name.lower()]


def find_conflicting_processes() -> list[str]:
    running: list[str] = []
    wanted = {name.lower(): label for name, label in CONFLICTING_PROCESSES.items()}

    for process in psutil.process_iter(["name"]):
        try:
            name = (process.info["name"] or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name in wanted and wanted[name] not in running:
            running.append(wanted[name])

    return running


def read_proxy() -> ProxyInfo:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_KEY) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return ProxyInfo(enabled=False)
            try:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            except FileNotFoundError:
                server = ""
            return ProxyInfo(enabled=True, server=str(server))
    except (FileNotFoundError, OSError):
        return ProxyInfo()


def disable_proxy() -> bool:
    """Выключает системный прокси — одна из починок, доступных по кнопке."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        return True
    except OSError:
        log.warning("Не удалось выключить системный прокси")
        return False


def path_has_cyrillic(path: Path) -> bool:
    return bool(_CYRILLIC_RE.search(str(path)))


def path_in_onedrive(path: Path) -> bool:
    # На Windows ключи окружения регистронезависимы и приводятся к верхнему регистру.
    onedrive = os.environ.get("ONEDRIVE") or os.environ.get("ONEDRIVECONSUMER")
    if not onedrive:
        return False
    try:
        return path.resolve().is_relative_to(Path(onedrive).resolve())
    except (OSError, ValueError):
        return False


def windivert_driver_present() -> bool:
    return any(paths.core_bin().glob("WinDivert*.sys")) if paths.core_bin().is_dir() else False


def collect() -> SystemFacts:
    """Собирает полный снимок состояния."""
    from app.core import elevation
    from app.core.diagnostics import vpn

    core = coreinfo.describe()
    names = all_service_names()
    tunnel = vpn.detect()
    instances = winws.find_instances()

    facts = SystemFacts(
        os_version=f"{platform.system()} {platform.release()} ({platform.version()})",
        is_admin=elevation.is_admin(),
        bfe_running=service.query_state("BFE") == "running",
        tcp_timestamps=service.tcp_timestamps_enabled(),
        proxy=read_proxy(),
        conflicting_services=find_conflicting_services(names),
        conflicting_processes=find_conflicting_processes(),
        vpn_services=find_vpn_services(names),
        active_vpn=tunnel.label if tunnel else "",
        core_present=core.present,
        core_version=core.version,
        core_path=str(core.path),
        strategy_count=core.strategy_count,
        available_strategies=[path.stem for path in strategies.discover()],
        windivert_driver_present=windivert_driver_present(),
        path_has_cyrillic=path_has_cyrillic(core.path),
        path_in_onedrive=path_in_onedrive(core.path),
        service_state=service.query_state(),
        service_strategy=service.installed_strategy(),
        windivert_state=service.windivert_state(),
        winws_count=len(instances),
        winws_cmdlines=[" ".join(instance.cmdline) for instance in instances],
        ipset_mode=ipset.status(),
        ipset_has_backup=ipset.has_backup(),
        game_filter=gamefilter.load().mode,
    )

    if core.present:
        facts.user_list_counts = {
            user_list.filename: len(lists.read(user_list).entries) for user_list in lists.USER_LISTS
        }

    return facts
