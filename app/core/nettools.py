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

# Что проверять послойно: пара заведомо фильтруемых и один свободный —
# без последнего «не работает ничего» не отличить от «интернета нет».
LAYER_HOSTS = ("rutracker.org", "www.youtube.com", "example.com")

# Куда стучаться. Несколько нарочно: один зашитый адрес у части
# провайдеров не отвечает вовсе, и проверка молчала бы без причины.
PING_TARGETS = ("1.1.1.1", "8.8.8.8", "77.88.8.8")
TRACE_HOPS = 12

# Свободный сайт для сравнения: если не открывается и он, дело не в блокировке,
# а в самом соединении. Берётся, когда человек проверяет свой адрес.
CONTROL_HOST = "example.com"

# Допустимое имя узла: буквы, цифры, дефис, точки. Начало с дефиса не пускаем
# вовсе: введённое попадает в аргументы `tracert`, и «-h 1» стало бы ключом.
_HOST_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*$")
_MAX_HOST = 253


def normalize_host(text: str) -> str:
    """Приводит введённое человеком к имени узла. Пусто — если на адрес не похоже.

    Принимает то, что люди вставляют на деле: адрес целиком с протоколом и путём
    (`https://instagram.com/user`), с портом, с заглавными буквами, кириллическое
    имя (`пример.рф`). Возвращает чистое имя без всего лишнего.

    Строгость здесь не придирка. Имя уходит в командную строку `tracert` и в
    запросы; пропустить в него пробел или дефис в начале значило бы дать
    человеку, сам того не зная, передать программе чужой ключ.
    """
    value = text.strip().lower()
    if not value:
        return ""

    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value)
    value = value.split("/")[0].split("?")[0].split("#")[0]
    value = value.rsplit("@", 1)[-1]
    if value.count(":") == 1:  # порт; у адресов IPv6 двоеточий больше, их не берём
        value = value.split(":")[0]
    value = value.strip(".")

    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError:
        return ""

    if not value or len(value) > _MAX_HOST or not _HOST_RE.match(value):
        return ""
    return value

@dataclass
class Outcome:
    """Что получилось. `ok` — всё хорошо, `warning` — есть на что смотреть."""

    title: str
    verdict: str = ""
    detail: str = ""
    level: str = "ok"
    lines: list[str] = field(default_factory=list)


def flush_command() -> list[str]:
    return ["ipconfig", "/flushdns"]


def trace_command(target: str, hops: int = TRACE_HOPS) -> list[str]:
    return ["tracert", "-d", "-h", str(hops), "-w", "800", target]


def mtu_command() -> list[str]:
    return ["netsh", "interface", "ipv4", "show", "subinterfaces"]


def shown(args: list[str]) -> str:
    """Команда так, как её набрали бы в консоли — для подсказки на кнопке.

    Строится из тех же списков аргументов, которые запускаются, а не пишется
    отдельной строкой: иначе подсказка рано или поздно описывала бы не то, что
    кнопка делает.
    """
    return " ".join(args)


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
        result = _run(flush_command(), timeout=20)
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


def where_blocked(host: str = "") -> Outcome:
    """Проверяет, на каком уровне рвётся связь: на своём адресе или на типичных.

    Берём и заведомо режущийся сайт, и заведомо свободный: без второго
    нельзя отличить «провайдер фильтрует» от «интернета нет вовсе». С адресом
    человека то же правило: рядом с ним проверяется свободный, иначе «не
    открывается» ничего не говорит.
    """
    from app.core.probe import layers

    hosts = (host, CONTROL_HOST) if host and host != CONTROL_HOST else LAYER_HOSTS
    results = [layers.check(name, _resolve_over_https(name)) for name in hosts]
    lines = [result.label for result in results]

    # Вердикт даём по самому «глубокому» найденному уровню: именно он
    # определяет, поможет ли здесь вообще стратегия обхода.
    order = (layers.Layer.DNS, layers.Layer.TCP, layers.Layer.TLS, layers.Layer.STUB)
    found = next(
        (level for level in order if any(item.layer is level for item in results)),
        None,
    )

    if found is None:
        return Outcome(
            "Где рвётся",
            "нигде — всё открывается",
            "Проверенные сайты отвечают нормально. Если что-то всё равно не "
            "работает, дело не в фильтрации на этих уровнях.",
            lines=lines,
        )

    return Outcome(
        "Где рвётся",
        layers.ADVICE[found].split(".")[0].lower(),
        layers.ADVICE[found],
        "warning",
        lines,
    )


def gateway() -> str:
    """Адрес шлюза по умолчанию.

    Берём из таблицы маршрутизации по числам: заголовки `route print`
    переведены на язык системы, а строка маршрута по умолчанию начинается
    с двух нулевых адресов на любой локали.
    """
    try:
        result = _run(["route", "print", "-4", "0.0.0.0"], timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""

    for line in result.stdout.splitlines():
        parts = line.split()
        if (
            len(parts) >= 3
            and parts[0] == "0.0.0.0"
            and parts[1] == "0.0.0.0"
            and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", parts[2])
        ):
            return parts[2]
    return ""


def _answers_ping(target: str, wait_ms: int = 1200) -> bool:
    """Отвечает ли узел на обычный ping. «TTL» в выводе не переводится."""
    if not target:
        return False
    try:
        result = _run(["ping", "-n", "1", "-w", str(wait_ms), target], timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return "TTL=" in result.stdout.upper()


def icmp_works() -> bool:
    """Проходит ли ICMP вообще.

    Спрашиваем сначала шлюз: он в локальной сети, и если молчит даже он,
    дело не в интернете, а в том, что такие пакеты режутся у нас — брандмауэром
    или адаптером VPN. Это сплошь и рядом, и двенадцать строк со звёздочками
    в ответ на трассировку ничего не объясняют.
    """
    return any(_answers_ping(host, 900) for host in (gateway(), *PING_TARGETS))


def trace(target: str = "", hops: int = TRACE_HOPS) -> Outcome:
    """Показывает путь до узла и где он обрывается."""
    if not icmp_works():
        return Outcome(
            "Трассировка",
            "ICMP не проходит",
            "Не отвечает даже шлюз вашей сети, а значит такие запросы режутся "
            "ещё до выхода наружу — чаще всего брандмауэром или адаптером VPN. "
            "Трассировка так работать не может, но о блокировках это ничего "
            "не говорит.",
        )

    target = target or next(
        (host for host in PING_TARGETS if _answers_ping(host)), PING_TARGETS[0]
    )

    try:
        result = _run(trace_command(target, hops), timeout=90)
    except (OSError, subprocess.SubprocessError) as error:
        return Outcome("Трассировка", "не удалось выполнить", str(error), "warning")

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    # Узлы — строки, начинающиеся с номера шага. Остальное, включая
    # заголовок, переведено на язык системы и разбору не подлежит.
    seen = [line for line in lines if re.match(r"^\d+\s", line)]
    answered = [line for line in seen if "*" not in line]

    if not seen:
        return Outcome("Трассировка", "путь не построился", "\n".join(lines[:4]), "warning")

    if not answered:
        return Outcome(
            "Трассировка",
            "ни один узел не ответил",
            f"До {target} не отозвался никто. Так бывает, когда весь путь "
            "идёт через туннель или провайдер режет такие запросы.",
            "warning",
        )

    return Outcome(
        "Трассировка",
        f"ответили {len(answered)} узлов из {len(seen)}",
        "Звёздочки — узел промолчал. Несколько подряд в середине пути это "
        "норма: многие маршрутизаторы не отвечают намеренно. Тревожно, когда "
        "путь обрывается сразу после вашего роутера.",
        lines=seen,
    )


def check_mtu() -> Outcome:
    """Показывает размер пакета у сетевых подключений.

    Спрашиваем у системы, а не подбираем пингом: ICMP режут и брандмауэр, и
    VPN, и подбор тогда не работает вовсе. Системе же этот размер известен
    точно — она его и назначает.
    """
    try:
        result = _run(mtu_command(), timeout=20)
    except (OSError, subprocess.SubprocessError) as error:
        return Outcome("Размер пакета", "узнать не удалось", str(error), "warning")

    found: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        # Строка начинается с MTU, дальше числа, последним — имя адаптера.
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        mtu = int(parts[0])
        name = " ".join(parts[4:])
        # Петлевой интерфейс объявляет заведомо неправдоподобный размер.
        if mtu > 10000 or "loopback" in name.lower():
            continue
        found.append((mtu, name))

    if not found:
        return Outcome("Размер пакета", "подключений не нашлось", level="warning")

    lines = [f"{name}: {mtu}" for mtu, name in sorted(found)]
    smallest, where = min(found)

    if smallest >= 1500:
        return Outcome(
            "Размер пакета",
            "обычный, 1500",
            "Пакеты проходят целиком — размер ничего не ломает.",
            lines=lines,
        )

    return Outcome(
        "Размер пакета",
        f"уменьшенный у «{where}»: {smallest}",
        "Через это подключение пакеты идут меньше обычного. Так устроены "
        "туннели VPN и подключения по PPPoE — само по себе это не поломка, "
        "но объясняет, почему страницы открываются, а крупные файлы качаются "
        "рывками.",
        "warning" if smallest < 1400 else "ok",
        lines,
    )
