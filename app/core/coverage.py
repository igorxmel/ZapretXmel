"""На какие сайты стратегия вообще влияет.

Стратегия срабатывает только для адресов из своих фильтров. Если сайта нет ни в списках, ни в
IP-наборе, winws его не трогает: сайт откроется или не откроется при любой стратегии, и его
проверка ничего о стратегии не говорит. Считать такой провал виной стратегии нельзя: подбор и
починка искали бы лекарство там, где его нет, и в конце жаловались бы на сайт.
"""

from __future__ import annotations

from app.core import ipset, lists, merge, strategies
from app.core.batfile import Section
from app.core.probe import services
from app.core.probe.services import ServiceResult

_NARROWING = ("--hostlist=", "--hostlist-domains=")
# Режим, в котором в IP-наборе лежит только адрес-заглушка, то есть секции по нему ничего не ловят.
IPSET_OFF = "none"


def host_is_covered(sections: list[Section], host: str, ipset_mode: str) -> bool:
    """Подействует ли стратегия на этот сайт при обычном соединении."""
    for section in sections:
        if not merge.section_matches(section, host, "tcp", 443):
            continue
        by_name = any(arg.startswith(_NARROWING) for arg in section.args)
        only_by_address = any(arg.startswith("--ipset=") for arg in section.args) and not by_name
        if not only_by_address or ipset_mode != IPSET_OFF:
            return True
    return False


def _sections() -> list[Section]:
    """Фильтры почти у всех стратегий сборки одинаковые, поэтому берём выбранную или любую."""
    names = [path.stem for path in strategies.discover()]
    for name in names:
        spec = strategies.load_one(name)
        if spec is not None:
            return spec.sections
    return []


def uncovered_target_names() -> frozenset[str]:
    """Цели, на которые стратегии не влияют: их провал не считается провалом стратегии."""
    sections = _sections()
    if not sections:
        return frozenset()
    mode = ipset.status()
    return frozenset(
        target.name
        for service in services.discover(include_discord_steps=False)
        for target in service.targets
        if not target.is_ping_only and not host_is_covered(sections, target.host, mode)
    )


def own_uncovered_hosts() -> list[str]:
    """Свои цели вне списков. Штатные цели человек не добавлял, и говорить о них незачем."""
    sections = _sections()
    if not sections:
        return []
    mode = ipset.status()
    hosts: list[str] = []
    for target in services.load_user_targets():
        if target.is_ping_only or target.host in hosts:
            continue
        if not host_is_covered(sections, target.host, mode):
            hosts.append(target.host)
    return hosts


def add_to_own_list(hosts: list[str]) -> int:
    """Дописывает домены в свой список. Возвращает, сколько добавилось.

    `www.` отбрасываем: домен в списке включает свои поддомены, так что запись получается шире и
    короче.
    """
    own = next(item for item in lists.USER_LISTS if item.filename == "list-general-user.txt")
    lists.ensure_user_lists()
    current = lists.read(own)
    fresh = [host.lower().removeprefix("www.") for host in hosts]
    fresh = [host for host in fresh if lists.validate(host, "domain")]
    # Заглушка нужна только пустому списку: с настоящей записью она лишняя.
    entries = [entry for entry in current.entries if entry != own.placeholder]
    return lists.write(own, [*entries, *fresh], current.comments) - len(entries)


def broken_services(results: list[ServiceResult], ignored: frozenset[str]) -> list[str]:
    """Сервисы, где не прошло то, на что стратегия могла повлиять."""
    return [
        result.service
        for result in results
        if result.measures_bypass
        and any(not check.ok and check.target not in ignored for check in result.checks)
    ]


def has_working_checks(results: list[ServiceResult], ignored: frozenset[str]) -> bool:
    return any(
        check.ok and check.target not in ignored
        for result in results
        if result.measures_bypass
        for check in result.checks
    )
