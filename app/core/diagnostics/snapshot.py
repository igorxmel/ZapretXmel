"""Снимок состояния для разбора — своего или чужим ИИ.

Собирает в один JSON всё, что нужно, чтобы понять, почему обход не работает:
обстановку, находки правил, состояние сборки и хвост лога. Тот же снимок идёт
и в пакет для внешней нейросети, и в запрос к подключённой — чтобы разбор
опирался ровно на одни и те же данные.

По умолчанию из снимка вычищается то, что указывает на конкретного человека:
имя пользователя в путях, внешний адрес, MAC. Диагностике эти данные не нужны,
а снимок нередко уходит наружу — в чат с нейросетью или в сообщение об ошибке.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict
from datetime import datetime
from typing import Any

from app.core import coreinfo, gamefilter, ipset, paths, service
from app.core.diagnostics import collectors, rules
from app.core.probe import autopick
from app.core.probe.http import supported_protocols

log = logging.getLogger(__name__)

LOG_TAIL_LINES = 120

_MAC_RE = re.compile(r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b", re.IGNORECASE)
# Адреса из частных диапазонов оставляем: они ничего не выдают, зато по ним
# видно, что трафик уходит в туннель.
_PUBLIC_IP_RE = re.compile(
    r"\b(?!10\.)(?!127\.)(?!169\.254\.)(?!192\.168\.)(?!172\.(?:1[6-9]|2\d|3[01])\.)"
    r"(?:\d{1,3}\.){3}\d{1,3}\b"
)

REDACTED = "<скрыто>"


def sanitize(value: Any, user: str | None = None) -> Any:
    """Убирает из данных то, что указывает на конкретного человека."""
    user = user if user is not None else os.environ.get("USERNAME", "")

    if isinstance(value, dict):
        return {key: sanitize(item, user) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item, user) for item in value]
    if not isinstance(value, str):
        return value

    text = value
    if user and len(user) > 2:
        # Границы слова обязательны: короткое имя вроде «user» иначе срабатывает
        # внутри обычных слов и превращает «C:\Users\...» в кашу.
        text = re.sub(rf"\b{re.escape(user)}\b", REDACTED, text, flags=re.IGNORECASE)
    text = _MAC_RE.sub(REDACTED, text)
    return _PUBLIC_IP_RE.sub(REDACTED, text)


def read_log_tail(lines: int = LOG_TAIL_LINES) -> list[str]:
    path = paths.logs_dir() / "app.log"
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def build(sanitized: bool = True, log_lines: int = LOG_TAIL_LINES) -> dict:
    """Собирает снимок состояния.

    Проверки по правилам выполняются здесь же: без них снимок — просто набор
    чисел, а с ними сразу видно, что система уже считает подозрительным.
    """
    facts = collectors.collect()
    findings = rules.evaluate(facts)
    core = coreinfo.describe()
    history = autopick.load_history(limit=1)

    snapshot: dict = {
        "собран": datetime.now().isoformat(timespec="seconds"),
        "обстановка": {
            "система": facts.os_version,
            "права администратора": facts.is_admin,
            "активный VPN": facts.active_vpn or "нет",
            "доступные протоколы": [name for name, _ in supported_protocols()],
        },
        "ядро": {
            "версия": core.version or "неизвестна",
            "установлено": core.present,
            "стратегий": core.strategy_count,
            "путь": str(core.path),
            "кириллица в пути": facts.path_has_cyrillic,
            "внутри OneDrive": facts.path_in_onedrive,
            "драйвер WinDivert на месте": facts.windivert_driver_present,
        },
        "обход": {
            "служба": service.LABELS.get(facts.service_state, facts.service_state),
            "стратегия службы": facts.service_strategy or "—",
            "процессов winws": facts.winws_count,
            "командные строки winws": facts.winws_cmdlines,
            "WinDivert": service.LABELS.get(facts.windivert_state, facts.windivert_state),
        },
        "настройки сборки": {
            "режим ipset": ipset.LABELS[facts.ipset_mode],
            "есть сохранённый список ipset": facts.ipset_has_backup,
            "игровой фильтр": gamefilter.load().label,
            "пользовательские списки": facts.user_list_counts,
        },
        "система": {
            "Base Filtering Engine": facts.bfe_running,
            "TCP timestamps": facts.tcp_timestamps,
            "системный прокси": facts.proxy.server if facts.proxy.enabled else "выключен",
            "конфликтующие службы": facts.conflicting_services,
            "конфликтующие программы": facts.conflicting_processes,
        },
        "находки": [
            {
                "важность": finding.severity.value,
                "что": finding.title,
                "подробности": finding.detail,
                "есть автофикс": bool(finding.fix),
            }
            for finding in findings
        ],
        "последний подбор": history[0] if history else None,
        "лог": read_log_tail(log_lines),
    }

    return sanitize(snapshot) if sanitized else snapshot


def problems_only(snapshot: dict) -> list[str]:
    """Короткий список проблем — им удобно открывать запрос к нейросети."""
    return [
        f"{item['что']}: {item['подробности']}".strip(": ")
        for item in snapshot.get("находки", [])
        if item.get("важность") in ("error", "warning")
    ]


def as_facts_dict() -> dict:
    """Сырые факты без истолкования — для тестов и отладки."""
    return asdict(collectors.collect())
