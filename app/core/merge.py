"""Сборка одной стратегии из частей нескольких.

Бывает, что одна стратегия чинит Discord, другая — YouTube, а обе сразу не
умеет никто. Стратегия устроена как цепочка секций, разделённых `--new`: у каждой
свой фильтр (порты, списки доменов, ipset) и свой способ обхода.

Просто склеить секции нельзя. winws берёт **первую подходящую**, а фильтры у
стратегий одной сборки совпадают дословно: секции второй стратегии не сработали
бы никогда, и «сборка» оказывалась копией первой.

Поэтому за основу берётся одна стратегия, и количество секций не меняется. Для
каждого сервиса определяем, какая секция основы его обслуживает, и подставляем
туда секцию с тем же фильтром от стратегии, выигравшей этот сервис.

Определить секцию можно лишь приблизительно: адрес в ipset без обращения к сети
не проверить, а сервис ходит не только на адреса из списка целей. Поэтому результат
считается кандидатом: его перемеряют вместе с исходными и оставляют, только если
он оказался лучше них (`is_improvement`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.core import paths
from app.core.batfile import Section, StrategySpec
from app.core.probe import services
from app.core.probe.autopick import Report

log = logging.getLogger(__name__)

KERNEL_PREFIX = "--wf-"
MERGED_SUFFIX = "сборка"
# Флаги, которые решают, к какому трафику относится секция.
SELECTOR_PREFIXES = ("--filter-", "--hostlist", "--ipset")
# Цели проверяются по HTTPS, а браузер ходит ещё и по QUIC.
_WEB_TRAFFIC = (("tcp", 443), ("udp", 443))
DISCORD_MARK = "discord"

# Перенос строки для .bat задаётся явно при записи. Если положить готовый CRLF
# прямо в текст, Python добавит к нему свой и выйдет двойной возврат каретки.
# От появившихся пустых строк разваливается склейка продолжений по «^»:
# командная строка обрывается сразу после winws.exe, и стратегия запускается
# вообще без аргументов.
WINDOWS_NEWLINE = "\r\n"


@dataclass(frozen=True)
class MergePlan:
    """Из чего собирается стратегия."""

    sources: dict[str, str] = field(default_factory=dict)

    @property
    def strategy_names(self) -> list[str]:
        """Исходные стратегии в порядке первого появления, без повторов."""
        seen: list[str] = []
        for name in self.sources.values():
            if name not in seen:
                seen.append(name)
        return seen

    @property
    def is_useful(self) -> bool:
        """Собирать есть смысл, только если сервисы выиграли разные стратегии."""
        return len(self.strategy_names) > 1

    def describe(self) -> str:
        return "; ".join(f"{service} — «{name}»" for service, name in self.sources.items())


@dataclass(frozen=True)
class Composition:
    """Что получилось собрать."""

    argv: list[str] = field(default_factory=list)
    base: str = ""
    # Описание заменённой секции → стратегия, откуда она взята.
    swapped: dict[str, str] = field(default_factory=dict)
    # Сервисы, которым досталась чужая секция: они делят её с другим победителем.
    conflicts: list[str] = field(default_factory=list)


def plan_from_winners(winners: dict[str, str]) -> MergePlan:
    """Строит план по словарю «сервис → лучшая для него стратегия».

    Порядок словаря сохраняется: его задаёт отчёт, и сервисы приходят от
    самого мелкого к крупному, чтобы узкие секции встали раньше широких.
    """
    return MergePlan(sources=dict(winners))


def kernel_flags(spec: StrategySpec) -> list[str]:
    return [arg for arg in spec.argv if arg.startswith(KERNEL_PREFIX)]


def rule_sections(spec: StrategySpec) -> list[Section]:
    """Секции стратегии без флагов уровня ядра."""
    cleaned: list[Section] = []
    for section in spec.sections:
        args = [arg for arg in section.args if not arg.startswith(KERNEL_PREFIX)]
        if args:
            cleaned.append(Section(args))
    return cleaned


def merge_kernel_flags(specs: list[StrategySpec]) -> list[str]:
    """Объединяет `--wf-*` всех стратегий, складывая списки портов.

    Повторы убираются, порядок первого появления сохраняется: winws принимает
    порты в произвольном порядке, а так результат легче читать и сравнивать.
    """
    merged: dict[str, list[str]] = {}

    for spec in specs:
        for flag in kernel_flags(spec):
            name, _, value = flag.partition("=")
            ports = merged.setdefault(name, [])
            for raw in value.split(","):
                token = raw.strip()
                if token and token not in ports:
                    ports.append(token)

    return [f"{name}={','.join(ports)}" for name, ports in merged.items() if ports]


def selector(section: Section) -> tuple[str, ...]:
    """Фильтр секции: две секции с одинаковым фильтром ловят один и тот же трафик."""
    return tuple(arg for arg in section.args if arg.startswith(SELECTOR_PREFIXES))


def _port_listed(value: str, port: int) -> bool:
    for piece in value.split(","):
        low, _, high = piece.strip().partition("-")
        if low.isdigit() and int(low) <= port <= int(high if high.isdigit() else low):
            return True
    return False


def _in_hostlist(host: str, path: str) -> bool:
    """Есть ли хост в файле списка. Поддомены входят в домен, как и у winws."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    return _in_domains(host, lines)


def _in_domains(host: str, domains: list[str]) -> bool:
    host = host.lower()
    for raw in domains:
        domain = raw.strip().lower()
        if not domain or domain.startswith("#"):
            continue
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def _excluded(flag: str, value: str, host: str) -> bool:
    if flag == "--hostlist-exclude":
        return _in_hostlist(host, value)
    return flag == "--hostlist-exclude-domains" and _in_domains(host, value.split(","))


def section_matches(section: Section, host: str, protocol: str, port: int) -> bool:
    """Подойдёт ли секция соединению — по тем же правилам, что у winws.

    Секция только с ipset считается подходящей: адрес без запроса к сети не
    узнать, а для запасной секции со всеми адресами это и так почти всегда верно.
    Секции с `--filter-l7` пропускаем: протокол определяется по самому трафику.
    """
    allowed = include = False
    for arg in section.args:
        flag, _, value = arg.partition("=")
        if flag == "--filter-l7":
            return False
        if flag == f"--filter-{protocol}":
            allowed = _port_listed(value, port)
        elif _excluded(flag, value, host):
            return False
        elif flag == "--hostlist":
            include = include or _in_hostlist(host, value)
        elif flag == "--hostlist-domains":
            include = include or _in_domains(host, value.split(","))

    if not allowed:
        return False
    narrowed = any(arg.startswith(("--hostlist=", "--hostlist-domains=")) for arg in section.args)
    return include or not narrowed


def sections_for_service(sections: list[Section], service: str, hosts: list[str]) -> set[int]:
    """Номера секций, через которые пойдёт трафик сервиса."""
    found: set[int] = set()
    for host in hosts:
        for protocol, port in _WEB_TRAFFIC:
            for index, section in enumerate(sections):
                if section_matches(section, host, protocol, port):
                    found.add(index)
                    break

    # Голос Discord идёт на свои порты, и по адресам сайта эти секции не найти.
    if DISCORD_MARK in service.lower():
        for index, section in enumerate(sections):
            if any(DISCORD_MARK in arg.rsplit("\\", 1)[-1].lower() for arg in selector(section)):
                found.add(index)
    return found


def service_hosts() -> dict[str, list[str]]:
    """Адреса проверок по сервисам — из тех же файлов целей, что у подбора."""
    return {
        service.name: [target.host for target in service.targets if not target.is_ping_only]
        for service in services.discover(include_discord_steps=False)
    }


def _base_strategy(plan: MergePlan, specs: dict[str, StrategySpec]) -> StrategySpec:
    """Основа — та, что выиграла больше сервисов: менять в ней придётся меньше."""
    wins = list(plan.sources.values())
    # При равенстве берём выигравшую сервис покрупнее: план идёт от мелких к крупным.
    name = max(reversed(wins), key=wins.count)
    return specs[name]


def compose(
    plan: MergePlan, specs: list[StrategySpec], hosts: dict[str, list[str]]
) -> Composition:
    """Собирает стратегию. Если заменить нечего, `argv` пуст и собирать незачем."""
    by_name = {spec.name: spec for spec in specs}
    base = _base_strategy(plan, by_name)
    sections = rule_sections(base)

    needed = {
        service: sections_for_service(sections, service, hosts.get(service, []))
        for service in plan.sources
    }

    # Сервисы основы занимают свои секции первыми: заменив такую секцию, мы
    # сломали бы то, что уже работает.
    owners: dict[int, tuple[str, str]] = {}
    ordered = sorted(plan.sources.items(), key=lambda item: item[1] != base.name)
    conflicts: list[str] = []
    for service, winner in ordered:
        for index in sorted(needed[service]):
            owner = owners.setdefault(index, (service, winner))
            if owner[1] != winner and service not in conflicts:
                conflicts.append(service)

    donors: list[StrategySpec] = []
    swapped: dict[str, str] = {}
    result: list[Section] = []
    for index, section in enumerate(sections):
        replacement = section
        winner = owners.get(index, ("", base.name))[1]
        if winner != base.name:
            donor = by_name[winner]
            same_filter = (s for s in rule_sections(donor) if selector(s) == selector(section))
            match = next(same_filter, None)
            if match is not None and match.args != section.args:
                replacement = match
                swapped[section.describe()] = winner
                if donor not in donors:
                    donors.append(donor)
        result.append(replacement)

    if not swapped:
        return Composition(base=base.name, conflicts=conflicts)

    # Флаги ядра встают в начало первой секции, а не отдельным блоком перед
    # «--new». Отдельный блок стал бы профилем без единого фильтра, то есть
    # подходящим под любой пакет, — и, по правилу «применяется первая
    # подходящая секция», затенил бы собой все остальные.
    argv: list[str] = merge_kernel_flags([base, *donors])
    for index, section in enumerate(result):
        if index:
            argv.append("--new")
        argv.extend(section.args)

    return Composition(argv=argv, base=base.name, swapped=swapped, conflicts=conflicts)


def is_improvement(report: Report, name: str) -> bool:
    """Оказалась ли сборка лучше исходных. Равенство — не повод плодить стратегии.

    `Report.best` при равенстве берёт ту, что мерили раньше, поэтому сборку
    мерят последней.
    """
    return not report.cancelled and report.best is not None and report.best.name == name


def merged_name(root: Path | None = None) -> str:
    """Свободное имя: прошлая сборка уже может быть выбрана и работать."""
    root = root or paths.core_dir()
    candidate = f"general ({MERGED_SUFFIX})"
    number = 2
    while (root / f"{candidate}.bat").exists():
        candidate = f"general ({MERGED_SUFFIX} {number})"
        number += 1
    return candidate


def is_merged(name: str) -> bool:
    return f"({MERGED_SUFFIX}" in name


def _quoted(arg: str) -> str:
    """Аргумент для .bat. Значение с пробелом без кавычек распалось бы на части."""
    if not any(char.isspace() for char in arg):
        return arg
    flag, sep, value = arg.partition("=")
    return f'{flag}="{value}"' if sep else f'"{arg}"'


def to_bat(argv: list[str], plan: MergePlan, root: Path | None = None) -> str:
    """Готовит содержимое .bat — такое же, как у штатных стратегий.

    Собранная стратегия сохраняется обычным файлом сборки, а не особой
    сущностью: тогда её видят и наш список стратегий, и консольное меню
    апстрима, и она переживает обновление ядра наравне с пользовательскими.
    """
    root = root or paths.core_dir()

    lines = [
        "@echo off",
        "chcp 65001 > nul",
        ":: Стратегия собрана программой ZapretXmel из частей:",
        f":: {plan.describe()}",
        ":: Её можно править руками — формат обычный.",
        "",
        'cd /d "%~dp0"',
        "",
        f'set "BIN={root / "bin"}\\"',
        "",
        'start "zapret: %~n0" /min "%BIN%winws.exe" ^',
    ]

    # Каждая секция — своей строкой, как в оригинальных файлах сборки:
    # так командную строку можно читать и править глазами.
    chunks: list[list[str]] = [[]]
    for arg in argv:
        chunks[-1].append(_quoted(arg))
        if arg == "--new":
            chunks.append([])

    body = [" ".join(chunk) for chunk in chunks if chunk]
    for index, line in enumerate(body):
        lines.append(line + (" ^" if index < len(body) - 1 else ""))

    return "\n".join(lines) + "\n"


def save(argv: list[str], plan: MergePlan, root: Path | None = None) -> Path:
    """Сохраняет собранную стратегию в папку ядра."""
    root = root or paths.core_dir()
    path = root / f"{merged_name(root)}.bat"
    path.write_text(to_bat(argv, plan, root), encoding="utf-8", newline=WINDOWS_NEWLINE)
    log.info("Собранная стратегия сохранена: %s", path.name)
    return path
