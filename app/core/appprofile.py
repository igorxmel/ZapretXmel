"""Профили приложений: пропустить через обход конкретную программу.

Сразу о главном ограничении, потому что от него зависит всё остальное.
**Фильтровать по процессу winws не умеет и не сможет.** WinDivert отдаёт
идентификатор процесса только на слоях FLOW, SOCKET и REFLECT, а winws работает
на слое NETWORK, где этого поля нет. Отбирать трафик он умеет по портам,
адресам и содержимому пакета.

Поэтому «выбрать игру» здесь означает другое: программа смотрит, **куда именно
ходит** выбранное приложение, и собирает из этого фильтр по портам и адресам.
Следствия честные и показываются в интерфейсе:

* другое приложение, которое пойдёт на те же адреса и порты, попадёт под те же
  правила — фильтр не знает, кто отправитель;
* игры с меняющимся пулом серверов потребуют повторной записи;
* списки адресов в winws живут в пользовательской памяти, поэтому размер стоит
  держать разумным.

Профиль поднимается **отдельным процессом winws** на узком фильтре. К WinDivert
можно прицепить несколько экземпляров, и так основная стратегия остаётся
нетронутой: сломанный профиль выключается одной кнопкой и ни на что больше не
влияет.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import socket
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import psutil

from app.core import paths
from app.core.batfile import Section, StrategySpec

log = logging.getLogger(__name__)

# Служебные адреса, которые есть у всех и ничего не говорят о приложении.
_IGNORED_PREFIXES = ("127.", "0.", "169.254.", "224.", "239.", "255.")

# Признак секции, рассчитанной на произвольный трафик: именно её настройки
# подходят профилю приложения, потому что протокол заранее неизвестен.
ANY_PROTOCOL_FLAG = "--dpi-desync-any-protocol"

PROFILE_SUFFIX = ".json"
_SAFE_NAME_RE = re.compile(r"[^\w .()\-]+", re.UNICODE)


@dataclass(frozen=True)
class AppInfo:
    """Запущенная программа, которую можно выбрать для записи."""

    pid: int
    name: str
    exe: str

    @property
    def label(self) -> str:
        return f"{self.name} (pid {self.pid})"


@dataclass(frozen=True)
class Endpoint:
    """Куда ходило приложение."""

    address: str
    port: int
    protocol: str

    @property
    def key(self) -> tuple[str, int, str]:
        return (self.address, self.port, self.protocol)


@dataclass
class Profile:
    """Собранный фильтр для одного приложения."""

    name: str
    exe: str = ""
    created_at: str = ""
    tcp_ports: list[int] = field(default_factory=list)
    udp_ports: list[int] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    source_strategy: str = ""
    # Поднимать профиль, когда приложение запустилось, и гасить, когда оно
    # закрылось. По умолчанию выключено: профиль — это ещё один экземпляр
    # winws, и включаться он должен осознанно.
    auto_start: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.addresses and (self.tcp_ports or self.udp_ports))

    @property
    def summary(self) -> str:
        parts = [f"адресов {len(self.addresses)}"]
        if self.tcp_ports:
            parts.append(f"TCP-портов {len(self.tcp_ports)}")
        if self.udp_ports:
            parts.append(f"UDP-портов {len(self.udp_ports)}")
        return ", ".join(parts)


def running_apps() -> list[AppInfo]:
    """Программы, у которых сейчас есть сетевые соединения.

    Показывать весь список процессов бессмысленно: выбирать нужно из того,
    что реально ходит в сеть.
    """
    active: dict[int, AppInfo] = {}

    for connection in psutil.net_connections(kind="inet"):
        if connection.pid is None or connection.pid in active:
            continue
        try:
            process = psutil.Process(connection.pid)
            active[connection.pid] = AppInfo(
                pid=connection.pid, name=process.name(), exe=process.exe() or ""
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return sorted(active.values(), key=lambda app: app.name.lower())


def process_tree(pid: int) -> set[int]:
    """Сам процесс и его потомки: лаунчеры часто запускают игру отдельно."""
    try:
        process = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return set()

    found = {pid}
    with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
        found.update(child.pid for child in process.children(recursive=True))
    return found


def is_useful(address: str) -> bool:
    """Отсеивает служебные и несетевые адреса."""
    if not address or ":" in address:  # IPv6 в ipset сборки не используется
        return False
    return not address.startswith(_IGNORED_PREFIXES)


class Recorder:
    """Накопитель соединений выбранного приложения.

    Соединения опрашиваются периодически, а не перехватываются: короткие
    обращения так можно пропустить, зато не нужен ни драйвер, ни права сверх
    тех, что уже есть. Для сбора портов и адресов этого достаточно.
    """

    def __init__(self, pid: int):
        self.pid = pid
        self.seen: Counter[tuple[str, int, str]] = Counter()
        self._pids = process_tree(pid)

    @property
    def endpoints(self) -> list[Endpoint]:
        return [
            Endpoint(address=address, port=port, protocol=protocol)
            for (address, port, protocol) in self.seen
        ]

    def refresh_tree(self) -> None:
        self._pids |= process_tree(self.pid)

    def sample(self) -> int:
        """Один опрос. Возвращает, сколько новых точек прибавилось."""
        before = len(self.seen)

        for connection in psutil.net_connections(kind="inet"):
            if connection.pid not in self._pids or not connection.raddr:
                continue
            address, port = connection.raddr[0], connection.raddr[1]
            if not is_useful(address):
                continue
            protocol = "tcp" if connection.type == socket.SOCK_STREAM else "udp"
            self.seen[(address, port, protocol)] += 1

        return len(self.seen) - before


def build_profile(
    name: str,
    endpoints: list[Endpoint],
    exe: str = "",
    min_hits: int = 1,
    counts: Counter | None = None,
) -> Profile:
    """Сворачивает наблюдения в фильтр.

    Одиночные обращения можно отсечь через `min_hits`: в записи обычно оседает
    телеметрия и проверки обновлений, которые к работе приложения отношения
    не имеют.
    """
    chosen = [
        endpoint
        for endpoint in endpoints
        if counts is None or counts.get(endpoint.key, 0) >= min_hits
    ]

    return Profile(
        name=name,
        exe=exe,
        created_at=datetime.now().isoformat(timespec="seconds"),
        tcp_ports=sorted({e.port for e in chosen if e.protocol == "tcp"}),
        udp_ports=sorted({e.port for e in chosen if e.protocol == "udp"}),
        addresses=sorted({e.address for e in chosen}),
    )


# --- хранение -----------------------------------------------------------


def profiles_dir() -> Path:
    return paths.data_dir() / "profiles"


def safe_name(name: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", name).strip() or "профиль"
    return cleaned[:60]


def profile_file(name: str) -> Path:
    return profiles_dir() / f"{safe_name(name)}{PROFILE_SUFFIX}"


def save(profile: Profile) -> Path:
    profiles_dir().mkdir(parents=True, exist_ok=True)
    path = profile_file(profile.name)
    path.write_text(json.dumps(asdict(profile), indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Профиль приложения сохранён: %s", path.name)
    return path


def load_all() -> list[Profile]:
    directory = profiles_dir()
    if not directory.is_dir():
        return []

    found: list[Profile] = []
    known = set(Profile.__dataclass_fields__)
    for path in sorted(directory.glob(f"*{PROFILE_SUFFIX}")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            found.append(Profile(**{k: v for k, v in data.items() if k in known}))
    return found


def delete(name: str) -> None:
    profile_file(name).unlink(missing_ok=True)


# --- превращение в команду winws ----------------------------------------


def ipset_file(profile: Profile) -> Path:
    return paths.core_lists() / f"ipset-{safe_name(profile.name)}-app.txt"


def write_ipset(profile: Profile) -> Path:
    """Складывает адреса профиля в отдельный файл ipset."""
    path = ipset_file(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(profile.addresses) + "\n", encoding="utf-8")
    return path


def pick_template(spec: StrategySpec) -> Section | None:
    """Выбирает из стратегии секцию, подходящую профилю.

    Нужна та, что рассчитана на произвольный протокол: какой именно трафик у
    приложения, заранее неизвестно. В сборках Flowseal это секции игрового
    фильтра — они помечены `--dpi-desync-any-protocol`. Если такой нет,
    берётся последняя: в этих файлах она самая общая.
    """
    for section in spec.sections:
        if any(arg.startswith(ANY_PROTOCOL_FLAG) for arg in section.args):
            return section
    return spec.sections[-1] if spec.sections else None


def desync_args(section: Section) -> list[str]:
    """Оставляет от секции только то, что относится к способу обхода."""
    return [
        arg
        for arg in section.args
        if not arg.startswith(("--filter-", "--hostlist", "--ipset", "--wf-"))
    ]


def to_argv(profile: Profile, spec: StrategySpec) -> list[str]:
    """Собирает командную строку для отдельного экземпляра winws."""
    template = pick_template(spec)
    if template is None:
        raise ValueError(f"в стратегии «{spec.name}» нет ни одной секции")

    ports = write_ipset(profile)
    settings = desync_args(template)

    argv: list[str] = []
    if profile.tcp_ports:
        argv.append("--wf-tcp=" + ",".join(str(port) for port in profile.tcp_ports))
    if profile.udp_ports:
        argv.append("--wf-udp=" + ",".join(str(port) for port in profile.udp_ports))

    first = True
    if profile.tcp_ports:
        argv += [
            "--filter-tcp=" + ",".join(str(port) for port in profile.tcp_ports),
            f"--ipset={ports}",
            *settings,
        ]
        first = False
    if profile.udp_ports:
        if not first:
            argv.append("--new")
        argv += [
            "--filter-udp=" + ",".join(str(port) for port in profile.udp_ports),
            f"--ipset={ports}",
            *settings,
        ]

    return argv


def as_spec(profile: Profile, spec: StrategySpec) -> StrategySpec:
    """Оформляет профиль как стратегию — её умеет запускать обычный WinwsProcess."""
    argv = to_argv(profile, spec)
    return StrategySpec(
        name=f"профиль: {profile.name}",
        path=profile_file(profile.name),
        argv=argv,
        sections=[Section(part) for part in _split_sections(argv)],
    )


def _split_sections(argv: list[str]) -> list[list[str]]:
    sections: list[list[str]] = [[]]
    for arg in argv:
        if arg == "--new":
            sections.append([])
            continue
        sections[-1].append(arg)
    return [section for section in sections if section]
