"""Что устарело: программа, ядро zapret, прокси для Telegram.

Три разных источника с тремя разными правилами сравнения версий собираются
здесь в один список — иначе человек узнаёт об обновлении, только если сам
догадается нажать кнопку в нужном разделе.

Ни одна неудача не считается ошибкой: GitHub может не ответить, а у части
провайдеров он и вовсе недоступен без обхода. Молчание в таком случае лучше
ругани — проверка не то, ради чего запускают программу.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core import coreinfo, telegram
from app.core.updater import github, selfupdate

log = logging.getLogger(__name__)

# Куда вести человека, который захочет обновиться.
APP = "программа"
CORE = "ядро zapret"
PROXY = "прокси для Telegram"


@dataclass(frozen=True)
class Available:
    """Найденное обновление."""

    what: str
    current: str
    latest: str
    section: str
    # Тот самый релиз, который мы уже спросили у GitHub. Нужен экрану
    # обновлений: без него он ничего не знает о находке и заставляет нажать
    # «Проверить» второй раз, хотя ответ получен минуту назад.
    release: github.Release | None = None

    @property
    def label(self) -> str:
        current = self.current or "не установлено"
        return f"{self.what}: {current} → {self.latest}"


def check_app() -> Available | None:
    if not selfupdate.is_frozen():
        return None

    release = selfupdate.check()
    if release is None:
        return None
    return Available(APP, selfupdate.current_version(), release.version, "updates", release)


def check_core() -> Available | None:
    info = coreinfo.describe()
    if not info.present:
        return None

    release = github.latest_release(github.CORE_REPO)
    if not github.is_newer(release.version, info.version):
        return None
    return Available(CORE, info.version, release.version, "updates", release)


def check_proxy() -> Available | None:
    if not telegram.is_installed():
        return None

    installed = telegram.installed_version()
    release = telegram.latest_release()

    # Прокси, поставленный до того, как мы стали запоминать версию, считаем
    # актуальным: предлагать обновление «с неизвестной на свежую» каждый раз
    # хуже, чем не предложить его один раз.
    if not installed or not github.is_newer(release.version, installed):
        return None
    return Available(PROXY, installed, release.version, "telegram", release)


def check_all() -> list[Available]:
    """Проверяет все три источника. Недоступный источник просто пропускается."""
    found: list[Available] = []

    for probe in (check_app, check_core, check_proxy):
        try:
            available = probe()
        except Exception:  # noqa: BLE001 — недоступный GitHub не повод шуметь
            log.info("Проверка обновлений не удалась: %s", probe.__name__, exc_info=True)
            continue

        if available is not None:
            found.append(available)

    if found:
        log.info("Доступны обновления: %s", ", ".join(item.label for item in found))
    return found


def summary(found: list[Available]) -> str:
    """Короткая строка для уведомления."""
    if not found:
        return ""
    if len(found) == 1:
        item = found[0]
        return f"Доступна новая версия: {item.what} {item.latest}"
    return "Доступны обновления: " + ", ".join(f"{item.what} {item.latest}" for item in found)
