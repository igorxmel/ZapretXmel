"""Сетевые проверки и действия, которые имеют отношение к блокировкам.

Это не набор «всё, что умеет Windows»: `netsh` и `ipconfig` умеют десятки
вещей, из которых к обходу относятся четыре. Остальное человеку здесь не
поможет, а список из двадцати кнопок помешает найти нужную.

Каждое действие отвечает на свой вопрос:

- кэш DNS — старые ответы остаются после правки hosts и смены DNS, и сайт
  продолжает не открываться, хотя всё уже настроено;
- подмена DNS — провайдеры отдают для заблокированных доменов свой адрес, и
  тогда обход бессилен: соединение уходит не туда;
- трассировка — где именно рвётся путь: у вас, у провайдера или дальше;
- MTU — слишком большие пакеты режутся молча, и это выглядит как «сайт
  открывается, а файлы не качаются».
"""

from __future__ import annotations

import logging
import re
import socket
import subprocess
from dataclasses import dataclass, field

from app.core.process import CREATE_NO_WINDOW, child_environment

log = logging.getLogger(__name__)

# Домен для проверки подмены: заблокирован у большинства провайдеров и при
# этом принадлежит крупной сети, адреса которой известны.
PROBE_DOMAIN = "rutracker.org"

# Куда идти трассировкой. Не «куда угодно»: нужен адрес, который точно
# отвечает и при этом проходит через весь путь до зарубежных сетей.
TRACE_TARGET = "1.1.1.1"
TRACE_HOPS = 12

# Размеры для подбора MTU, от потолка к низу. 1472 — предел обычного
# Ethernet с учётом заголовков; через VPN проходит заметно меньше, а у
# WireGuard-туннелей потолок опускается до 1300 и ниже. Снизу 1172, потому
# что меньше не бывает у работающего подключения.
MTU_SIZES = (1472, 1452, 1420, 1372, 1340, 1300, 1272, 1232, 1172)


@dataclass
class Outcome:
    """Что получилось. `ok` — всё хорошо, `warning` — есть на что смотреть."""

    title: str
    verdict: str = ""
    detail: str = ""
    level: str = "ok"
    lines: list[str] = field(default_factory=list)


def _run(args: list[str], timeout: int = 40) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 — фиксированные системные утилиты
        args,
        capture_output=True,
        text=True,
        encoding="cp866",
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        env=child_environment(),
        check=False,
    )


def flush_dns() -> Outcome:
    """Сбрасывает кэш DNS.

    Вывод `ipconfig` переведён на язык системы, поэтому смотрим только на
    код возврата: разбирать его по русским или английским словам нельзя.
    """
    try:
        result = _run(["ipconfig", "/flushdns"], timeout=20)
    except (OSError, subprocess.SubprocessError) as error:
        return Outcome("Кэш DNS", "не удалось сбросить", str(error), "warning")

    if result.returncode != 0:
        return Outcome(
            "Кэш DNS",
            "не удалось сбросить",
            result.stdout.strip() or result.stderr.strip(),
            "warning",
        )

    return Outcome(
        "Кэш DNS",
        "сброшен",
        "Старые ответы больше не используются. Если сайт не открывался "
        "после правки hosts или смены DNS — попробуйте ещё раз.",
    )


def check_dns(domain: str = PROBE_DOMAIN) -> Outcome:
    """Сравнивает ответ системного DNS с ответом через DNS-over-HTTPS.

    Провайдер подменяет ответы только в своём DNS: запрос по HTTPS до него
    не доходит, потому что он зашифрован и идёт на чужой сервер. Разошлись
    ответы — значит подменяет, и обход тут бессилен: соединение уходит не
    туда ещё до того, как winws увидит хоть один пакет.
    """
    try:
        system = sorted({info[4][0] for info in socket.getaddrinfo(domain, 443)})
    except OSError as error:
        return Outcome(
            "Подмена DNS",
            "имя не разрешается вовсе",
            f"Система не смогла найти адрес {domain}: {error}. Чаще всего "
            "это значит, что DNS провайдера отвечает отказом — поможет "
            "смена DNS на публичный.",
            "warning",
        )

    honest = _resolve_over_https(domain)
    if not honest:
        return Outcome(
            "Подмена DNS",
            "проверить не удалось",
            "Не получилось спросить независимый DNS — он сам может быть "
            "заблокирован. Включите обход и попробуйте снова.",
            "warning",
            [f"Системный ответ: {', '.join(system)}"],
        )

    if set(system) & set(honest):
        return Outcome(
            "Подмена DNS",
            "не обнаружена",
            "Системный DNS отвечает тем же, что и независимый.",
            lines=[f"Ответ: {', '.join(system)}"],
        )

    return Outcome(
        "Подмена DNS",
        "похоже, провайдер подменяет ответы",
        "Системный DNS отдаёт не те адреса, что независимый. Обход здесь "
        "не поможет: соединение уходит не туда ещё до него. Смените DNS в "
        "настройках сети на публичный — например 1.1.1.1 или 8.8.8.8.",
        "warning",
        [f"Системный: {', '.join(system)}", f"Независимый: {', '.join(honest)}"],
    )


def _resolve_over_https(domain: str) -> list[str]:
    """Спрашивает адрес у Cloudflare по HTTPS — в обход провайдерского DNS."""
    import requests

    try:
        response = requests.get(
            "https://cloudflare-dns.com/dns-query",
            params={"name": domain, "type": "A"},
            headers={"Accept": "application/dns-json"},
            timeout=15,
        )
        response.raise_for_status()
        answers = response.json().get("Answer", [])
    except Exception:  # noqa: BLE001 — недоступность тоже бывает ответом
        log.debug("Независимый DNS не ответил", exc_info=True)
        return []

    return sorted({item["data"] for item in answers if item.get("type") == 1})


def trace(target: str = TRACE_TARGET, hops: int = TRACE_HOPS) -> Outcome:
    """Показывает путь до узла и где он обрывается."""
    try:
        result = _run(
            ["tracert", "-d", "-h", str(hops), "-w", "800", target], timeout=90
        )
    except (OSError, subprocess.SubprocessError) as error:
        return Outcome("Трассировка", "не удалось выполнить", str(error), "warning")

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    # Узлы — строки, начинающиеся с номера шага. Остальное, включая
    # заголовок, переведено на язык системы и разбору не подлежит.
    hops_seen = [line for line in lines if re.match(r"^\d+\s", line)]
    lost = [line for line in hops_seen if "*" in line]

    if not hops_seen:
        return Outcome("Трассировка", "путь не построился", "\n".join(lines[:4]), "warning")

    verdict = f"пройдено узлов: {len(hops_seen)}"
    detail = (
        "Звёздочки — узел не ответил. Несколько подряд в середине пути это "
        "норма: многие маршрутизаторы молчат намеренно. Тревожно, когда путь "
        "обрывается на первом же шаге после вашего роутера."
    )
    level = "warning" if len(lost) > len(hops_seen) // 2 else "ok"
    return Outcome("Трассировка", verdict, detail, level, hops_seen)


def _answers_ping(target: str) -> bool:
    """Отвечает ли узел на обычный ping. «TTL» в выводе не переводится."""
    try:
        result = _run(["ping", "-n", "1", "-w", "1500", target], timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return "TTL=" in result.stdout.upper()


def check_mtu(target: str = TRACE_TARGET) -> Outcome:
    """Подбирает наибольший размер пакета, который проходит без дробления.

    Сначала проверяем, отвечает ли узел вообще: ICMP режут и провайдеры, и
    VPN, и тогда ни один размер не пройдёт — но сказать это надо прямо, а
    не выдавать за найденную неисправность.
    """
    if not _answers_ping(target):
        return Outcome(
            "Размер пакета",
            "проверить нечем",
            f"Узел {target} не отвечает на ping вовсе. Такие запросы режут "
            "и провайдеры, и VPN — о вашей сети это ничего не говорит, но и "
            "размер пакета так не измерить.",
        )

    passed = 0
    for size in MTU_SIZES:
        try:
            result = _run(["ping", "-n", "1", "-f", "-l", str(size), target], timeout=20)
        except (OSError, subprocess.SubprocessError) as error:
            return Outcome("Размер пакета", "проверить не удалось", str(error), "warning")

        # Код возврата у ping нулевой и при потере пакета, поэтому смотрим
        # на наличие ответа: слово «TTL» в выводе не переводится.
        if "TTL=" in result.stdout.upper():
            passed = size
            break

    if not passed:
        return Outcome(
            "Размер пакета",
            "проходят только совсем мелкие",
            f"Узел отвечает, но ни один размер от {MTU_SIZES[-1]} байт и "
            "выше не дошёл. Так бывает при неверно настроенном туннеле — "
            "страницы при этом открываются, а файлы качаются рывками.",
            "warning",
        )

    mtu = passed + 28  # заголовки IP и ICMP
    if mtu >= 1500:
        return Outcome(
            "Размер пакета",
            f"обычный, {mtu}",
            "Пакеты проходят целиком — размер ничего не ломает.",
        )

    return Outcome(
        "Размер пакета",
        f"уменьшенный, {mtu}",
        "Пакеты полного размера не проходят. Так бывает через VPN и "
        "PPPoE-подключения; само по себе это не поломка, но объясняет, "
        "почему страницы открываются, а крупные файлы качаются рывками.",
        "warning" if mtu < 1400 else "ok",
    )
