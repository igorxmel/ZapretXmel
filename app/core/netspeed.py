"""Сколько сейчас принимается и отдаётся по сети.

Нужно на главном экране по одной причине: когда интернет лежит, виноватой
назначают программу — она ведь «что-то делает с сетью». Строка «сети нет»
рядом с состоянием обхода снимает этот вопрос раньше, чем он возникнет.

Меряем не пропускную способность канала, а то, что идёт прямо сейчас:
проверка скорости качала бы десятки мегабайт ради цифры, а счётчики
интерфейсов уже ведёт сама Windows и стоят они ничего.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import psutil

log = logging.getLogger(__name__)

# Ниже этого считаем, что сети нет вовсе: у живого соединения всегда идёт
# служебный фон, а полный ноль означает оборванный кабель или отключённый
# адаптер.
SILENT_BYTES = 0


@dataclass(frozen=True)
class Speed:
    """Байты в секунду в обе стороны."""

    received: float = 0.0
    sent: float = 0.0
    online: bool = True

    @property
    def label(self) -> str:
        if not self.online:
            return "сети нет"
        return f"приём {human(self.received)} · отдача {human(self.sent)}"


def human(per_second: float) -> str:
    """Скорость словами: килобайты до мегабайта, дальше мегабайты."""
    if per_second < 1024:
        return f"{per_second:.0f} Б/с"
    if per_second < 1024 * 1024:
        return f"{per_second / 1024:.0f} КБ/с"
    return f"{per_second / (1024 * 1024):.1f} МБ/с"


class Meter:
    """Счётчик скорости между двумя опросами.

    Состояние держится здесь, а не в глобальной переменной: опрос идёт в
    фоновом потоке, и два измерителя рядом не должны мешать друг другу.
    """

    def __init__(self):
        self._at = 0.0
        self._received = 0
        self._sent = 0

    def read(self) -> Speed:
        """Скорость с прошлого вызова. Первый вызов отдаёт нули."""
        try:
            counters = psutil.net_io_counters()
            online = _has_link()
        except Exception:  # noqa: BLE001 — счётчики не повод падать
            log.debug("Счётчики сети недоступны", exc_info=True)
            return Speed(online=False)

        now = time.monotonic()
        received, sent = counters.bytes_recv, counters.bytes_sent

        previous_at, self._at = self._at, now
        previous_received, self._received = self._received, received
        previous_sent, self._sent = self._sent, sent

        passed = now - previous_at
        if not previous_at or passed <= 0:
            return Speed(online=online)

        # Счётчики сбрасываются при перезапуске адаптера — отрицательная
        # разница значит именно это, а не отрицательную скорость.
        return Speed(
            received=max(0.0, (received - previous_received) / passed),
            sent=max(0.0, (sent - previous_sent) / passed),
            online=online,
        )


def _has_link() -> bool:
    """Есть ли хоть один поднятый сетевой интерфейс, кроме петлевого.

    Это ответ на вопрос «подключён ли компьютер к сети», а не «работает ли
    интернет»: второе проверяют пробы по сервисам, и делать это каждые
    несколько секунд ради строки на экране незачем.
    """
    try:
        stats = psutil.net_if_stats()
    except Exception:  # noqa: BLE001
        return True

    return any(
        state.isup and not name.lower().startswith(("loopback", "lo"))
        for name, state in stats.items()
    )
