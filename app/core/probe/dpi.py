"""Обнаружение блокировки по реальной передаче данных.

Обычная проверка `HEAD`-запросом отвечает лишь на вопрос «открывается ли
страница». У большинства провайдеров она открывается и без обхода — режут не
её, а поток данных: видео с googlevideo, голос в Discord. Поэтому проверка
по HEAD легко показывает сплошные успехи там, где на деле ничего не работает.

Здесь используется методика, на которую опирается и консольный тестер апстрима:
набор хостов из [dpi-checkers](https://github.com/hyperion-cs/dpi-checkers)
(Apache-2.0), на каждый отправляется POST с телом в несколько килобайт и
запрашивается диапазон байт в ответ. Смотрим не код ответа, а сколько байт
реально ушло и пришло. Характерная картина блокировки — запрос ушёл целиком,
ответ не пришёл вовсе, и соединение провисело до самого таймаута.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import requests

from app.core.probe.http import (
    CREATE_NO_WINDOW,
    CURL,
    CurlMissingError,
    curl_available,
    supported_protocols,
)

log = logging.getLogger(__name__)

SUITE_URL = "https://hyperion-cs.github.io/dpi-checkers/ru/tcp-16-20/suite.v2.json"

DEFAULT_RANGE_BYTES = 16 * 1024
DEFAULT_TIMEOUT = 8

_MEASURE_RE = re.compile(r"^(?P<code>\d{3})\s+(?P<up>\d+)\s+(?P<down>\d+)\s+(?P<time>[\d.]+)$")
_UNSUPPORTED_RE = re.compile(
    r"not supported|does not support|unsupported protocol|unsupported option"
    r"|unrecognized option|unknown option|unsupported feature|schannel|ssl",
    re.IGNORECASE,
)
_EXIT_SSL_CONNECT_ERROR = 35


class DpiStatus(StrEnum):
    OK = "OK"
    FAIL = "FAIL"
    UNSUPPORTED = "UNSUP"
    LIKELY_BLOCKED = "BLOCKED"


LABELS: dict[DpiStatus, str] = {
    DpiStatus.OK: "данные прошли",
    DpiStatus.FAIL: "соединение не удалось",
    DpiStatus.UNSUPPORTED: "протокол не поддержан",
    DpiStatus.LIKELY_BLOCKED: "похоже на блокировку",
}


@dataclass(frozen=True)
class DpiTarget:
    """Хост из проверочного набора."""

    id: str
    provider: str
    country: str
    host: str

    @property
    def title(self) -> str:
        return f"{self.country} {self.id} ({self.provider})".strip()


@dataclass(frozen=True)
class DpiLine:
    """Результат одной пробы: один хост, один протокол."""

    protocol: str
    code: str
    up_bytes: int
    down_bytes: int
    seconds: float
    status: DpiStatus


@dataclass(frozen=True)
class DpiResult:
    target: DpiTarget
    lines: list[DpiLine]

    @property
    def ok_count(self) -> int:
        return sum(1 for line in self.lines if line.status is DpiStatus.OK)

    @property
    def blocked_count(self) -> int:
        return sum(1 for line in self.lines if line.status is DpiStatus.LIKELY_BLOCKED)


def load_suite(timeout: int = 20) -> list[DpiTarget]:
    """Скачивает список проверочных хостов.

    Набор живёт снаружи и пополняется его авторами — поэтому он не зашит
    в код, как и всё остальное, что может поменяться без нашего участия.
    """
    response = requests.get(SUITE_URL, timeout=timeout)
    response.raise_for_status()

    targets: list[DpiTarget] = []
    for item in response.json():
        host = (item.get("host") or "").strip()
        if not host:
            continue
        targets.append(
            DpiTarget(
                id=item.get("id", host),
                provider=item.get("provider", ""),
                country=item.get("country", ""),
                host=host,
            )
        )
    return targets


def make_payload(size: int = DEFAULT_RANGE_BYTES) -> Path:
    """Создаёт файл со случайными байтами — телом POST-запроса."""
    descriptor, name = tempfile.mkstemp(prefix="zapretxmel-", suffix=".bin")
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(secrets.token_bytes(size))
    return Path(name)


def _classify(
    exit_code: int,
    text: str,
    up_bytes: int,
    down_bytes: int,
    seconds: float,
    timeout: int,
) -> tuple[str, DpiStatus]:
    """Определяет исход пробы по количеству переданных байт.

    Отдельно выделяется картина «запрос ушёл, ответа нет, провисели до
    таймаута» — так выглядит обрыв соединения оборудованием провайдера,
    а не обычная сетевая ошибка.
    """
    match = _MEASURE_RE.match(text)

    if match:
        code = match.group("code")
    elif exit_code == _EXIT_SSL_CONNECT_ERROR or _UNSUPPORTED_RE.search(text):
        return "UNSUP", DpiStatus.UNSUPPORTED
    elif text:
        code = "ERR"
    else:
        code = "NA"

    if up_bytes > 0 and down_bytes == 0 and seconds >= timeout and exit_code != 0:
        return code, DpiStatus.LIKELY_BLOCKED

    if exit_code != 0 or code in ("ERR", "NA"):
        return code, DpiStatus.FAIL

    return code, DpiStatus.OK


def probe(
    target: DpiTarget,
    protocol: str,
    args: tuple[str, ...],
    payload: Path,
    range_bytes: int = DEFAULT_RANGE_BYTES,
    timeout: int = DEFAULT_TIMEOUT,
) -> DpiLine:
    """Одна проба: POST с телом и запросом диапазона байт в ответе."""
    if not curl_available():
        raise CurlMissingError(f"не найден {CURL}")

    command = [
        str(CURL),
        "--range",
        f"0-{range_bytes - 1}",
        "-m",
        str(timeout),
        "--connect-timeout",
        str(min(3, timeout)),
        "-w",
        "%{http_code} %{size_upload} %{size_download} %{time_total}",
        "-o",
        "NUL",
        "-X",
        "POST",
        "--data-binary",
        f"@{payload}",
        "-s",
        *args,
        f"https://{target.host}",
    ]

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
        exit_code = completed.returncode
        text = (completed.stdout + completed.stderr).strip()
    except subprocess.TimeoutExpired:
        exit_code, text = 28, ""
    except OSError as error:
        exit_code, text = 1, str(error)

    up_bytes = down_bytes = 0
    seconds = -1.0
    if match := _MEASURE_RE.match(text):
        up_bytes = int(match.group("up"))
        down_bytes = int(match.group("down"))
        seconds = float(match.group("time"))

    code, status = _classify(exit_code, text, up_bytes, down_bytes, seconds, timeout)
    return DpiLine(
        protocol=protocol,
        code=code,
        up_bytes=up_bytes,
        down_bytes=down_bytes,
        seconds=max(seconds, 0.0),
        status=status,
    )


def check_target(
    target: DpiTarget,
    payload: Path,
    range_bytes: int = DEFAULT_RANGE_BYTES,
    timeout: int = DEFAULT_TIMEOUT,
) -> DpiResult:
    """Проверяет один хост всеми протоколами."""
    lines = [
        probe(target, name, args, payload, range_bytes, timeout)
        for name, args in supported_protocols()
    ]
    return DpiResult(target=target, lines=lines)
