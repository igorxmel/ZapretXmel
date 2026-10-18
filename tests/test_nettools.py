"""Тесты сетевых проверок.

Сами команды трогают систему, поэтому проверяется разбор их вывода — там и
была ошибка: вывод `netsh` и `route` переведён на язык системы, и опираться
можно только на числа.
"""

from __future__ import annotations

import pytest

from app.core import nettools

SUBINTERFACES = """
   MTU  Состояние  Вх. байт  Исх. байт  Интерфейс
------  ---------  --------  ---------  ----------
4294967295          1         0   28593803  Loopback Pseudo-Interface 1
  1380          1  7069760681  2289030299  AmneziaVPN
  1500          1  73299519895  23278423491  Ethernet
"""

ROUTE = """
===========================================================================
Активные маршруты:
Сетевой адрес           Маска сети      Адрес шлюза       Интерфейс  Метрика
          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.108     35
          0.0.0.0          0.0.0.0         On-link          10.8.1.2      5
"""


def fake_run(output: str):
    """Подменяет запуск системной утилиты заранее известным выводом."""
    result = type("Result", (), {"stdout": output, "stderr": "", "returncode": 0})()
    return lambda *args, **kwargs: result


def test_mtu_is_read_from_the_system(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подбор пингом не работает там, где ICMP режут, — а режут часто."""
    monkeypatch.setattr(nettools, "_run", fake_run(SUBINTERFACES))

    outcome = nettools.check_mtu()

    assert "1380" in outcome.verdict
    assert "AmneziaVPN" in outcome.verdict


def test_loopback_does_not_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Петлевой интерфейс объявляет заведомо неправдоподобный размер."""
    monkeypatch.setattr(nettools, "_run", fake_run(SUBINTERFACES))

    outcome = nettools.check_mtu()

    assert not any("Loopback" in line for line in outcome.lines)


def test_gateway_is_found_by_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заголовки `route print` переведены, а нули маршрута — нет."""
    monkeypatch.setattr(nettools, "_run", fake_run(ROUTE))

    assert nettools.gateway() == "192.168.1.1"


def test_blocked_icmp_is_said_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Двенадцать строк со звёздочками ничего не объясняют.

    ICMP режут и брандмауэр, и адаптер VPN — это сплошь и рядом, и сказать
    об этом надо один раз и прямо, а не показывать пустую трассировку.
    """
    monkeypatch.setattr(nettools, "icmp_works", lambda: False)

    outcome = nettools.trace()

    assert outcome.verdict == "ICMP не проходит"
    assert outcome.level == "ok", "это не поломка сети, а её настройка"
