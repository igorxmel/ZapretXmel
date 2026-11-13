"""Быстрая проверка: работает ли обход прямо сейчас.

Главный вопрос у человека, включившего обход, — «ну и как, работает?».
Подбор стратегии на него отвечает, но за минуты, а диагностика проверяет
систему, а не сервисы. Здесь ровно одна задача: за пару секунд сказать, что
сейчас открывается, а что нет.

Состав сервисов тот же, что у подбора, — из файлов целей сборки, так что
новый сервис у апстрима появится здесь сам. Никакого замера без обхода тут
нет и быть не может: мы не выбираем лучшее из вариантов, а смотрим на то,
что есть сейчас.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.core import coverage
from app.core.probe import services
from app.core.probe.services import ServiceResult

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuickCheck:
    """Чем закончилась быстрая проверка."""

    results: list[ServiceResult] = field(default_factory=list)
    # Цели, на которые стратегия не влияет. Их провал не считается поломкой обхода
    # (`app/core/coverage.py`), но человеку о нём говорится отдельно.
    ignored: frozenset[str] = frozenset()

    @property
    def judged(self) -> list[ServiceResult]:
        """Сервисы, по которым вообще можно судить об обходе.

        Группа из одних пингов (у апстрима это «Public DNS (PING-only)») сюда
        не входит: winws работает на TCP и UDP, к ICMP не прикасается, и её
        результат одинаков с обходом и без него. Подробнее — в
        `Service.measures_bypass`.
        """
        return [result for result in self.results if result.measures_bypass]

    def _passed(self, result: ServiceResult) -> bool | None:
        """Прошёл ли сервис. None: все его цели вне списков, и судить не о чем."""
        if not result.checks:
            return False
        covered = [check for check in result.checks if check.target not in self.ignored]
        return all(check.ok for check in covered) if covered else None

    @property
    def working(self) -> list[str]:
        return [result.service for result in self.judged if self._passed(result) is True]

    @property
    def broken(self) -> list[str]:
        """Сервисы, где прошло не всё.

        Частично прошедший сервис считается сломанным намеренно: Discord, у
        которого открывается сайт, но не подключается клиент, работающим не
        назовёшь.
        """
        return [result.service for result in self.judged if self._passed(result) is False]

    @property
    def outside_lists_failed(self) -> list[str]:
        """Цели вне списков, которые не открылись: обход тут ни при чём, но сайт-то закрыт."""
        names = [
            check.target
            for result in self.judged
            for check in result.checks
            if not check.ok and check.target in self.ignored
        ]
        return list(dict.fromkeys(names))

    @property
    def everything_works(self) -> bool:
        return bool(self.working) and not self.broken

    @property
    def no_ping(self) -> bool:
        """Не прошли пинги — сами по себе это не поломка, но сказать стоит."""
        return any(
            not result.measures_bypass and result.dead and result.total
            for result in self.results
        )

    @property
    def notes(self) -> list[str]:
        """Оговорки к результату — словами, а не внутренними терминами.

        «Не открылось вне списков: CloudflareCDN» понять было нельзя. Речь о
        сайтах, которых нет в списках обхода: стратегия их не трогает, и если
        они не открылись, дело не в ней.
        """
        found = []
        if outside := self.outside_lists_failed:
            found.append(
                f"Не открылось {', '.join(outside)}, но этого нет в списках обхода — "
                "стратегия тут ни при чём, скорее сеть или провайдер."
            )
        if self.no_ping:
            found.append("Пинг не проходит, но обхода это не касается.")
        return found

    @property
    def verdict(self) -> str:
        if not self.judged:
            return "проверять нечего — не нашлось ни одной цели"

        # Про пинги говорим в конце и отдельной оговоркой: иначе человек
        # читает «не работает Public DNS» как «обход сломан» и идёт чинить
        # то, что не ломалось. Чаще всего ICMP просто режет брандмауэр.
        tail = " · пинг не проходит, но обхода это не касается" if self.no_ping else ""
        if outside := self.outside_lists_failed:
            tail = f" · не открылось вне списков: {', '.join(outside)}" + tail

        if self.everything_works:
            return "всё работает: " + ", ".join(self.working) + tail
        if not self.working:
            return "не работает ничего из проверенного" + tail
        return (
            "не работает: "
            + ", ".join(self.broken)
            + " · работает: "
            + ", ".join(self.working)
            + tail
        )


def run(timeout: int = 5, parallel: int = 8) -> QuickCheck:
    """Проверяет все сервисы разом и возвращает короткий вердикт."""
    found = services.discover()
    if not found:
        return QuickCheck()

    # Потоки распределяются и между сервисами, и внутри каждого: иначе
    # сервис с восемью целями проверяется восемь таймаутов подряд, и
    # «быстрая» проверка занимает полминуты.
    with ThreadPoolExecutor(max_workers=max(1, len(found))) as pool:
        results = list(
            pool.map(lambda service: services.check(service, timeout, parallel), found)
        )

    check = QuickCheck(results=results, ignored=coverage.uncovered_target_names())
    log.info("Быстрая проверка: %s", check.verdict)
    _log_failures(check)
    return check


def _log_failures(check: QuickCheck) -> None:
    """Что именно не прошло. По одному «не работает: YouTube» причину не найти."""
    for result in check.judged:
        for item in result.checks:
            if not item.ok:
                log.info("  %s, %s: %s", result.service, item.name, item.reason or item.detail)
