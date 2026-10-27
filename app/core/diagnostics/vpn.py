"""Распознавание активного VPN-подключения.

Пока трафик идёт через туннель, любые проверки обхода бессмысленны: они меряют
VPN, а не вашего провайдера. Подобранная в таком состоянии «лучшая» стратегия
окажется случайной — она просто не помешала туннелю.

Факт установленного VPN-клиента здесь не интересен. Важно одно: уходит ли
наружу трафик через туннель прямо сейчас.
"""

from __future__ import annotations

import logging
import socket
import subprocess
from dataclasses import dataclass

import psutil

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
_ENCODINGS = ("utf-8", "cp866", "cp1251")

# Признаки туннельного адаптера в его имени или описании. Список покрывает
# распространённые клиенты; при промахе остаётся запасной признак — маршрут по
# умолчанию без шлюза, характерный для туннелей.
VPN_MARKERS = (
    "vpn",
    "wireguard",
    "wintun",
    "amnezia",
    "openvpn",
    "tap-windows",
    "tap adapter",
    "tunnel",
    "tailscale",
    "zerotier",
    "hamachi",
    "outline",
    "proton",
    "nordlynx",
    "mullvad",
    "warp",
    "cloudflare",
    "shadowsocks",
    "ppp",
    "l2tp",
    "sstp",
    "ikev2",
)


@dataclass(frozen=True)
class VpnInfo:
    """Активное туннельное подключение."""

    adapter: str
    description: str = ""

    @property
    def label(self) -> str:
        if self.description and self.description.lower() != self.adapter.lower():
            return f"{self.adapter} ({self.description})"
        return self.adapter


def _decode(raw: bytes) -> str:
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def looks_like_tunnel(*names: str) -> bool:
    haystack = " ".join(name.lower() for name in names if name)
    return any(marker in haystack for marker in VPN_MARKERS)


def outbound_address() -> str:
    """IP-адрес, который система выберет для выхода в интернет.

    Сокет никуда не отправляет данных — он нужен лишь затем, чтобы спросить у
    таблицы маршрутизации, через какой интерфейс пойдёт трафик.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return ""
    finally:
        probe.close()


def adapter_for_address(address: str) -> str:
    """Имя сетевого адаптера, которому принадлежит адрес."""
    if not address:
        return ""
    for name, addresses in psutil.net_if_addrs().items():
        for entry in addresses:
            if entry.family == socket.AF_INET and entry.address == address:
                return name
    return ""


def _default_route_adapter() -> tuple[str, str]:
    """Адаптер маршрута по умолчанию и его описание, по данным PowerShell.

    Имена свойств PowerShell не локализуются, поэтому разбор не зависит от
    языка системы — в отличие от вывода `route print`.
    """
    command = (
        "$r = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | "
        "Sort-Object RouteMetric,InterfaceMetric | Select-Object -First 1; "
        "if ($r) { $a = Get-NetAdapter -InterfaceIndex $r.ifIndex -ErrorAction SilentlyContinue; "
        "Write-Output ($r.InterfaceAlias + '|' + $a.InterfaceDescription) }"
    )
    try:
        completed = subprocess.run(  # noqa: S603 — фиксированная команда без пользовательского ввода
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", ""

    line = _decode(completed.stdout).strip().splitlines()
    if not line:
        return "", ""

    alias, _, description = line[0].partition("|")
    return alias.strip(), description.strip()


# Описания адаптеров по их именам. Имя адаптера клиент выбирает сам: у Clash
# Verge оно «Meta», и узнать туннель можно только по описанию («Meta Tunnel»).
# PowerShell зовём один раз на каждое новое имя, а не при каждом опросе.
_descriptions: dict[str, str] = {}


def _adapter_descriptions() -> dict[str, str]:
    command = (
        "Get-NetAdapter -ErrorAction SilentlyContinue | "
        "ForEach-Object { $_.Name + '|' + $_.InterfaceDescription }"
    )
    try:
        completed = subprocess.run(  # noqa: S603 — фиксированная команда без пользовательского ввода
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    found: dict[str, str] = {}
    for line in _decode(completed.stdout).splitlines():
        name, _, description = line.partition("|")
        if name.strip():
            found[name.strip()] = description.strip()
    return found


def adapter_description(adapter: str) -> str:
    if adapter not in _descriptions:
        _descriptions.update(_adapter_descriptions())
        # Не нашли — запоминаем пустоту, чтобы не звать PowerShell снова и снова.
        _descriptions.setdefault(adapter, "")
    return _descriptions[adapter]


def detect_fast() -> VpnInfo | None:
    """Быстрая проверка для опроса состояния по таймеру.

    Адаптер узнаётся по исходящему адресу мгновенно. Описание адаптера
    запрашивается один раз на имя и дальше берётся из памяти: без него не
    узнать туннель, названный клиентом нейтрально («Meta», «Clash»).
    """
    adapter = adapter_for_address(outbound_address())
    if not adapter:
        return None
    if looks_like_tunnel(adapter):
        return VpnInfo(adapter=adapter)

    description = adapter_description(adapter)
    if looks_like_tunnel(description):
        return VpnInfo(adapter=adapter, description=description)
    return None


def detect() -> VpnInfo | None:
    """Возвращает сведения о туннеле, через который сейчас идёт трафик.

    Сначала спрашиваем маршрут по умолчанию — это точный ответ на вопрос «куда
    на самом деле уходит трафик». Если PowerShell недоступен, опознаём адаптер
    по исходящему адресу: менее подробно, зато без внешних вызовов.
    """
    alias, description = _default_route_adapter()
    if alias and looks_like_tunnel(alias, description):
        return VpnInfo(adapter=alias, description=description)

    return detect_fast()
