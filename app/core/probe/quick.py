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

from app.core.probe import services
from app.core.probe.services import ServiceResult

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuickCheck:
    """Чем закончилась быстрая проверка."""

    results: list[ServiceResult] = field(default_factory=list)

    @property
    def working(self) -> list[str]:
        return [result.service for result in self.results if result.works]

    @property
    def broken(self) -> list[str]:
        """Сервисы, где прошло не всё.

        Частично прошедший сервис считается сломанным намеренно: Discord, у
        которого открывается сайт, но не подключается клиент, работающим не
        назовёшь.
        """
        return [result.service for result in self.results if not result.works]

    @property
    def everything_works(self) -> bool:
        return bool(self.results) and not self.broken

    @property
    def verdict(self) -> str:
        if not self.results:
            return "проверять нечего — не нашлось ни одной цели"
        if self.everything_works:
            return "всё работает: " + ", ".join(self.working)
        if not self.working:
            return "не работает ничего из проверенного"
        return (
            "не работает: "
            + ", ".join(self.broken)
            + " · работает: "
            + ", ".join(self.working)
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

    check = QuickCheck(results=results)
    log.info("Быстрая проверка: %s", check.verdict)
    return check
