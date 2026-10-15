"""Проверка Discord по частям.

Discord ломается не целиком: страница `discord.com` обычно открывается у всех,
и обычная проверка показывает успех, пока клиент висит на «Connecting…».
Отдельно проверяются те шаги, которые клиент делает на самом деле:

1. запрос к API — без него не начинается вход;
2. рукопожатие WebSocket с гейтвеем — именно здесь вход и застревает;
3. доступность CDN — по ней грузятся аватарки и вложения.

Голос проверить так нельзя: он идёт по UDP на адреса, которые выдаются уже
после входа в канал. Поэтому про него интерфейс говорит отдельно.
"""

from __future__ import annotations

import base64
import logging
import secrets
import socket
import ssl
import time
from dataclasses import dataclass
from enum import StrEnum

import requests

log = logging.getLogger(__name__)

API_GATEWAY = "https://discord.com/api/v10/gateway"
GATEWAY_HOST = "gateway.discord.gg"
GATEWAY_PATH = "/?v=10&encoding=json"
CDN_URL = "https://cdn.discordapp.com/embed/avatars/0.png"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DEFAULT_TIMEOUT = 8


class Step(StrEnum):
    API = "api"
    GATEWAY = "gateway"
    CDN = "cdn"


STEP_TITLES: dict[Step, str] = {
    Step.API: "Запрос к API Discord",
    Step.GATEWAY: "Подключение к гейтвею (вход в аккаунт)",
    Step.CDN: "Загрузка картинок и вложений",
}

STEP_MEANING: dict[Step, str] = {
    Step.API: "Не работает — клиент не начнёт вход вообще.",
    Step.GATEWAY: "Не работает — клиент бесконечно висит на «Connecting…».",
    Step.CDN: "Не работает — не грузятся аватарки, картинки и файлы.",
}


@dataclass(frozen=True)
class StepResult:
    step: Step
    ok: bool
    detail: str = ""
    elapsed_ms: float = 0.0

    @property
    def title(self) -> str:
        return STEP_TITLES[self.step]

    @property
    def meaning(self) -> str:
        return STEP_MEANING[self.step]


def _timed(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


def check_api(timeout: int = DEFAULT_TIMEOUT) -> StepResult:
    started = time.monotonic()
    try:
        response = requests.get(
            API_GATEWAY, timeout=timeout, headers={"User-Agent": USER_AGENT}
        )
        ok = response.status_code == 200 and "url" in response.text
        detail = f"код {response.status_code}"
    except requests.RequestException as error:
        ok, detail = False, type(error).__name__
    return StepResult(Step.API, ok, detail, _timed(started))


def check_gateway(host: str = GATEWAY_HOST, timeout: int = DEFAULT_TIMEOUT) -> StepResult:
    """Выполняет настоящее рукопожатие WebSocket, как это делает клиент.

    Обычный HTTPS-запрос сюда не годится: гейтвей отвечает на него 404, и
    проверка считает, что всё хорошо, хотя апгрейд соединения может рваться.
    """
    started = time.monotonic()
    key = base64.b64encode(secrets.token_bytes(16)).decode()
    request = (
        f"GET {GATEWAY_PATH} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"User-Agent: {USER_AGENT}\r\n"
        "\r\n"
    )

    try:
        context = ssl.create_default_context()
        with (
            socket.create_connection((host, 443), timeout) as raw,
            context.wrap_socket(raw, server_hostname=host) as tls,
        ):
            tls.sendall(request.encode())
            answer = tls.recv(4096).decode("utf-8", errors="replace")
    except (OSError, ssl.SSLError) as error:
        return StepResult(Step.GATEWAY, False, type(error).__name__, _timed(started))

    first_line = answer.split("\r\n", 1)[0] if answer else "пустой ответ"
    ok = "101" in first_line
    return StepResult(Step.GATEWAY, ok, first_line[:80], _timed(started))


def check_cdn(timeout: int = DEFAULT_TIMEOUT) -> StepResult:
    started = time.monotonic()
    try:
        response = requests.get(
            CDN_URL, timeout=timeout, headers={"User-Agent": USER_AGENT}
        )
        ok = response.status_code == 200 and len(response.content) > 0
        detail = f"код {response.status_code}, {len(response.content)} байт"
    except requests.RequestException as error:
        ok, detail = False, type(error).__name__
    return StepResult(Step.CDN, ok, detail, _timed(started))


def check_all(timeout: int = DEFAULT_TIMEOUT) -> list[StepResult]:
    return [check_api(timeout), check_gateway(timeout=timeout), check_cdn(timeout)]


def summarise(results: list[StepResult]) -> str:
    """Короткий вывод: что именно сломано и чем это проявляется."""
    broken = [result for result in results if not result.ok]
    if not broken:
        return (
            "Все проверяемые части Discord отвечают. Если клиент всё равно не работает, "
            "дело в голосовом трафике: он идёт по UDP, и его чинят секции стратегии "
            "с фильтрами по портам 50000-50100 и 19294-19344."
        )
    return "Не отвечает: " + "; ".join(f"{r.title.lower()} — {r.meaning.lower()}" for r in broken)
