"""Сервисы — то, ради чего обход и нужен.

Подбирать стратегию «по ютубу» или «по дискорду» по отдельности неправильно:
у одного провайдера режут одно, у другого другое, а пользователю нужно, чтобы
работало всё сразу. Поэтому проверка идёт сразу по всем сервисам, а итог
показывается по каждому отдельно — и если лучшая стратегия что-то так и не
починила, об этом говорится прямо, а не прячется в общей сумме.

Состав сервисов не зашит в код: он берётся из заголовков-групп в
`core/utils/targets.txt`, а свои можно дописать в `targets-user.txt` рядом.
Исключение одно — Discord: вместо запроса его главной страницы выполняется
пошаговая проверка клиента, потому что страница открывается и тогда, когда
сам Discord не работает.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.core import paths
from app.core.probe import discord
from app.core.probe.http import Outcome, check_target
from app.core.probe.targets import Target, load, parse

log = logging.getLogger(__name__)

Kind = Literal["http", "discord"]

# Группа, которую заменяет пошаговая проверка клиента Discord.
DISCORD_GROUP = "Discord"

USER_TARGETS_NAME = "targets-user.txt"

USER_TARGETS_TEMPLATE = """\
# Свои цели для подбора стратегии.
#
# Заголовок со знаками ### задаёт сервис — по нему будет отдельная оценка.
# Строка вида Имя = "https://адрес" проверяет сайт, PING: — только отклик.
#
### Мои сайты
# Example = "https://example.com"
"""


@dataclass(frozen=True)
class CheckResult:
    """Результат одной проверки внутри сервиса."""

    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class ServiceResult:
    """Как сервис чувствует себя при текущей стратегии."""

    service: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def ok_count(self) -> int:
        return sum(1 for check in self.checks if check.ok)

    @property
    def works(self) -> bool:
        """Сервис считается рабочим, только когда прошли все его проверки."""
        return self.total > 0 and self.ok_count == self.total

    @property
    def dead(self) -> bool:
        return self.total > 0 and self.ok_count == 0

    @property
    def label(self) -> str:
        return f"{self.service} {self.ok_count}/{self.total}"


@dataclass(frozen=True)
class Service:
    """Набор проверок, объединённых общим смыслом."""

    name: str
    kind: Kind = "http"
    targets: list[Target] = field(default_factory=list)

    @property
    def size(self) -> int:
        # У Discord три шага; у обычного сервиса — по числу целей.
        return 3 if self.kind == "discord" else len(self.targets)


def user_targets_file() -> Path:
    return paths.core_utils() / USER_TARGETS_NAME


def ensure_user_targets() -> None:
    """Создаёт файл для своих целей с пояснением, если его ещё нет."""
    path = user_targets_file()
    if path.exists() or not path.parent.is_dir():
        return
    path.write_text(USER_TARGETS_TEMPLATE, encoding="utf-8")


def load_user_targets() -> list[Target]:
    path = user_targets_file()
    if not path.exists():
        return []
    try:
        return parse(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []


def discover(include_discord_steps: bool = True) -> list[Service]:
    """Собирает сервисы из групп в файлах целей.

    Цели без группы складываются в сервис «Прочее», иначе они потерялись бы.
    """
    grouped: dict[str, list[Target]] = {}
    for target in [*load(), *load_user_targets()]:
        grouped.setdefault(target.group or "Прочее", []).append(target)

    services: list[Service] = []
    for name, targets in grouped.items():
        if include_discord_steps and name == DISCORD_GROUP:
            # Страницы Discord открываются и при неработающем клиенте —
            # поэтому здесь проверяются шаги входа, а не доступность сайта.
            services.append(Service(name=DISCORD_GROUP, kind="discord"))
            continue
        services.append(Service(name=name, targets=targets))

    if include_discord_steps and not any(s.name == DISCORD_GROUP for s in services):
        services.append(Service(name=DISCORD_GROUP, kind="discord"))

    return services


def check(service: Service, timeout: int = 6, parallel: int = 1) -> ServiceResult:
    """Выполняет проверки сервиса.

    По умолчанию цели проверяются по очереди: в подборе стратегий это
    принципиально, иначе проверки мешают друг другу и время перестаёт быть
    сравнимым между стратегиями. Быстрая проверка ничего не сравнивает,
    поэтому может попросить несколько потоков и уложиться в пару секунд.
    """
    if service.kind == "discord":
        return ServiceResult(
            service=service.name,
            checks=[
                CheckResult(name=step.title, ok=step.ok, detail=step.detail)
                for step in discord.check_all(timeout=timeout)
            ],
        )

    if parallel > 1 and len(service.targets) > 1:
        with ThreadPoolExecutor(max_workers=min(parallel, len(service.targets))) as pool:
            outcomes = list(pool.map(lambda t: check_target(t, timeout=timeout), service.targets))
    else:
        outcomes = [check_target(target, timeout=timeout) for target in service.targets]

    checks: list[CheckResult] = []
    for target, result in zip(service.targets, outcomes, strict=True):
        if not result.probes:
            # Цель только для пинга: другого признака работоспособности нет.
            checks.append(
                CheckResult(
                    name=target.name,
                    ok=result.ping_ms is not None,
                    detail="пинг" if result.ping_ms is not None else "нет отклика",
                )
            )
            continue

        for probe in result.probes:
            checks.append(
                CheckResult(
                    name=f"{target.name} · {probe.protocol}",
                    ok=probe.outcome is Outcome.OK,
                    detail=str(probe.outcome),
                )
            )

    return ServiceResult(service=service.name, checks=checks)
