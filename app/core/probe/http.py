"""HTTP- и TLS-пробы через системный curl.

Берём ту же методику, что и консольный тестер апстрима: каждая цель
проверяется тремя способами — обычный HTTP/1.1 и принудительные TLS 1.2 и
TLS 1.3. Разные версии TLS блокируются по-разному, поэтому стратегия, которая
чинит одну из них, но ломает другую, видна сразу.

Отдельно выделяется исход SSL: если вместо сайта приходит чужой сертификат или
имя не резолвится, виноват не обход, а подмена DNS — менять стратегию
бесполезно, и интерфейс говорит об этом прямо.
"""

from __future__ import annotations

import functools
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.core.probe.icmp import ping
from app.core.probe.targets import Target

log = logging.getLogger(__name__)

CURL = Path(r"C:\Windows\System32\curl.exe")
CREATE_NO_WINDOW = 0x08000000

# curl возвращает 35 при неподдерживаемой версии TLS в Schannel.
_EXIT_SSL_CONNECT_ERROR = 35

_SSL_PATTERNS = re.compile(
    r"could not resolve host|certificate|self[- ]?signed|verify failed|local issuer",
    re.IGNORECASE,
)
_UNSUPPORTED_PATTERNS = re.compile(
    r"does not support|not supported|unsupported protocol|unsupported option"
    r"|unrecognized option|unknown option|unsupported feature",
    re.IGNORECASE,
)


class Outcome(StrEnum):
    OK = "OK"
    ERROR = "ERROR"
    UNSUPPORTED = "UNSUP"
    SSL = "SSL"


LABELS: dict[Outcome, str] = {
    Outcome.OK: "работает",
    Outcome.ERROR: "не отвечает",
    Outcome.UNSUPPORTED: "протокол не поддержан",
    Outcome.SSL: "подмена сертификата или DNS",
}

# Протоколы в том же наборе, что и у апстримного тестера.
PROTOCOLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("HTTP", ("--http1.1",)),
    ("TLS1.2", ("--tlsv1.2", "--tls-max", "1.2")),
    ("TLS1.3", ("--tlsv1.3", "--tls-max", "1.3")),
)

# Хост для разовой проверки возможностей curl. Нужен заведомо живой и не
# попадающий под блокировки, иначе проверка спутает «протокол не умеем»
# с «сайт недоступен».
_CAPABILITY_HOST = "https://www.gstatic.com"


@functools.cache
def supported_protocols() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Протоколы, которые системный curl действительно умеет.

    В Windows 10 curl собран со Schannel, и `--tls-max 1.3` там отвергается:
    «TLS 1.3 not supported on Windows prior to 11». Если не отсеять такой
    протокол заранее, каждая стратегия получит треть заведомо бесполезных
    проб — время прогона вырастет, а в результатах появятся числа, которые
    невозможно сойтись.
    """
    if not curl_available():
        return PROTOCOLS

    usable: list[tuple[str, tuple[str, ...]]] = []
    for name, args in PROTOCOLS:
        command = [
            str(CURL), "-I", "-s", "--show-error", "-o", "NUL",
            "-m", "8", "--connect-timeout", "4", *args, _CAPABILITY_HOST,
        ]
        try:
            completed = subprocess.run(  # noqa: S603 — фиксированный путь к системному curl
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                creationflags=CREATE_NO_WINDOW,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            usable.append((name, args))  # сеть подвела — протокол не виноват
            continue

        if _UNSUPPORTED_PATTERNS.search(completed.stderr):
            log.info("curl не поддерживает %s — проба отключена", name)
            continue
        usable.append((name, args))

    return tuple(usable) or PROTOCOLS


@dataclass(frozen=True)
class ProbeResult:
    """Исход одной пробы — одна цель, один протокол."""

    target: str
    protocol: str
    outcome: Outcome
    http_code: str = ""
    elapsed_ms: float = 0.0
    detail: str = ""


@dataclass(frozen=True)
class TargetResult:
    """Все пробы по одной цели плюс пинг."""

    target: Target
    probes: list[ProbeResult]
    ping_ms: float | None = None

    @property
    def ok_count(self) -> int:
        return sum(1 for probe in self.probes if probe.outcome is Outcome.OK)

    @property
    def has_ssl_problem(self) -> bool:
        return any(probe.outcome is Outcome.SSL for probe in self.probes)


class CurlMissingError(Exception):
    """В системе нет curl.exe — проверки выполнить нечем."""


def curl_available() -> bool:
    return CURL.exists()


def _classify(returncode: int, stderr: str) -> Outcome:
    if _SSL_PATTERNS.search(stderr):
        return Outcome.SSL
    if returncode == _EXIT_SSL_CONNECT_ERROR or _UNSUPPORTED_PATTERNS.search(stderr):
        return Outcome.UNSUPPORTED
    if returncode == 0:
        return Outcome.OK
    return Outcome.ERROR


def probe(target: Target, protocol: str, args: tuple[str, ...], timeout: int = 5) -> ProbeResult:
    """Выполняет одну пробу и классифицирует результат."""
    if not curl_available():
        raise CurlMissingError(f"не найден {CURL}")

    command = [
        str(CURL),
        "-I",
        "-s",
        "--show-error",
        "-o",
        "NUL",
        "-w",
        "%{http_code}",
        "-m",
        str(timeout),
        "--connect-timeout",
        str(min(2, timeout)),
        *args,
        target.url,
    ]

    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 — фиксированный путь к системному curl
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout + 5,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        returncode, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired:
        returncode, stdout, stderr = 28, "", "timeout"
    except OSError as error:
        returncode, stdout, stderr = 1, "", str(error)

    elapsed = (time.monotonic() - started) * 1000
    return ProbeResult(
        target=target.name,
        protocol=protocol,
        outcome=_classify(returncode, stderr),
        http_code=stdout.strip(),
        elapsed_ms=round(elapsed, 1),
        detail=stderr.strip()[:200],
    )


def check_target(target: Target, timeout: int = 5, ping_timeout_ms: int = 1000) -> TargetResult:
    """Полная проверка одной цели: три протокола плюс пинг."""
    probes: list[ProbeResult] = []
    if target.url:
        probes = [probe(target, name, args, timeout) for name, args in supported_protocols()]

    latency = ping(target.host, ping_timeout_ms) if target.host else None
    return TargetResult(target=target, probes=probes, ping_ms=latency)
