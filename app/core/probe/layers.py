"""На каком уровне рвётся соединение: DNS, TCP, TLS или ответ сервера.

Главный вопрос пользователя звучит не «работает ли сайт», а «почему обход
включён, а сайт всё равно не открывается». Ответ на него зависит от того,
где именно обрывается связь, и зависимость эта жёсткая:

- **DNS** — провайдер отдаёт не тот адрес. Обход тут бессилен: соединение
  уходит не туда ещё до того, как winws увидит первый пакет. Лечится сменой
  DNS, а не стратегией.
- **TCP** — соединение рвут на уровне адреса. Стратегии почти не помогают,
  нужен VPN или другой адрес сервиса.
- **TLS** — соединение устанавливается, а рукопожатие обрывается. Это и есть
  фильтрация по имени сайта, ровно то, ради чего существует zapret: другая
  стратегия здесь действительно может помочь.
- **Заглушка** — сервер ответил страницей провайдера. Тоже дело стратегии,
  но иногда и просто устаревшие списки.

Подход послойной проверки подсмотрен у
[rkn-block-checker](https://github.com/MayersScott/rkn-block-checker)
(проверяет уровни по очереди и останавливается на первом отказе). Код свой:
вендорить ради сотни строк нечего, а лишний сайдкар — это ещё и его
обновления, и его размер.
"""

from __future__ import annotations

import logging
import socket
import ssl
from dataclasses import dataclass
from enum import StrEnum

log = logging.getLogger(__name__)

TIMEOUT = 6.0
HTTPS_PORT = 443

# Признаки страницы-заглушки провайдера. Текст у всех разный, но набор слов
# повторяется: это не список провайдеров, а список формулировок.
STUB_MARKS = (
    "ограничен",
    "заблокирован",
    "единый реестр",
    "решению суда",
    "роскомнадзор",
    "zapret-info",
    "blocked",
)


class Layer(StrEnum):
    """Где оборвалось. Порядок — порядок проверки."""

    OK = "ok"
    DNS = "dns"
    TCP = "tcp"
    TLS = "tls"
    STUB = "stub"
    UNKNOWN = "unknown"


# Что это значит для обхода — то единственное, ради чего проверка и нужна.
ADVICE: dict[Layer, str] = {
    Layer.OK: "Открывается без помех.",
    Layer.DNS: (
        "Провайдер подменяет адрес сайта. Обход здесь бессилен: соединение "
        "уходит не туда ещё до него. Смените DNS на публичный — 1.1.1.1 или "
        "8.8.8.8."
    ),
    Layer.TCP: (
        "Соединение рвут по адресу сервера. Стратегии обхода тут помогают "
        "редко: обычно нужен VPN."
    ),
    Layer.TLS: (
        "Соединение устанавливается, но обрывается на имени сайта — это и "
        "есть то, ради чего нужен zapret. Попробуйте другую стратегию: "
        "подбор найдёт рабочую."
    ),
    Layer.STUB: (
        "Отвечает страница-заглушка провайдера. Помогает стратегия обхода, "
        "а если сайт свежий — добавьте его в «Списки»."
    ),
    Layer.UNKNOWN: "Причина не определилась — сайт мог просто не отвечать.",
}


@dataclass(frozen=True)
class LayerResult:
    """Чем закончилась проверка одного адреса."""

    host: str
    layer: Layer
    detail: str = ""

    @property
    def label(self) -> str:
        titles = {
            Layer.OK: "работает",
            Layer.DNS: "подмена DNS",
            Layer.TCP: "рвётся соединение",
            Layer.TLS: "режется по имени сайта",
            Layer.STUB: "заглушка провайдера",
            Layer.UNKNOWN: "непонятно",
        }
        return f"{self.host}: {titles[self.layer]}"


def check(host: str, honest_addresses: list[str] | None = None) -> LayerResult:
    """Проверяет уровни по очереди и останавливается на первом отказе.

    `honest_addresses` — адреса, полученные независимо (через DNS поверх
    HTTPS). Если они есть и не пересекаются с системными, дальше идти
    бессмысленно: мы уже знаем, что пойдём не туда.
    """
    try:
        addresses = sorted({info[4][0] for info in socket.getaddrinfo(host, HTTPS_PORT)})
    except OSError as error:
        return LayerResult(host, Layer.DNS, f"имя не разрешается: {error}")

    if honest_addresses and not set(addresses) & set(honest_addresses):
        return LayerResult(
            host,
            Layer.DNS,
            f"система отдаёт {', '.join(addresses)}, независимый DNS — "
            f"{', '.join(honest_addresses)}",
        )

    try:
        connection = socket.create_connection((addresses[0], HTTPS_PORT), TIMEOUT)
    except OSError as error:
        return LayerResult(host, Layer.TCP, str(error))

    with connection:
        context = ssl.create_default_context()
        # Проверка сертификата здесь выключена нарочно: нас интересует,
        # доходит ли рукопожатие вообще, а не кому принадлежит сертификат.
        # Иначе самоподписанный сертификат заглушки выглядел бы как обрыв.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        try:
            secured = context.wrap_socket(connection, server_hostname=host)
        except (ssl.SSLError, OSError) as error:
            return LayerResult(host, Layer.TLS, str(error))

        with secured:
            return _ask_http(secured, host)


def _ask_http(secured: ssl.SSLSocket, host: str) -> LayerResult:
    """Запрашивает страницу и смотрит, не заглушка ли пришла в ответ."""
    request = (
        f"GET / HTTP/1.1\r\nHost: {host}\r\n"
        "User-Agent: ZapretXmel\r\nConnection: close\r\n\r\n"
    ).encode()

    try:
        secured.sendall(request)
        secured.settimeout(TIMEOUT)
        answer = secured.recv(4096)
    except OSError as error:
        # Рукопожатие прошло, а данные не идут — так тоже выглядит фильтр.
        return LayerResult(host, Layer.TLS, f"ответ не пришёл: {error}")

    if not answer:
        return LayerResult(host, Layer.TLS, "сервер закрыл соединение молча")

    text = answer.decode("utf-8", "replace").lower()
    if " 451 " in text[:40] or any(mark in text for mark in STUB_MARKS):
        return LayerResult(host, Layer.STUB, text.splitlines()[0][:80])

    return LayerResult(host, Layer.OK, text.splitlines()[0][:80])
