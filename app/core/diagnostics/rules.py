"""Движок правил: превращает собранные факты в понятные находки.

Полный перенос проверок из `service.bat` плюс те, которых у апстрима нет:
рассогласование выбранной и установленной стратегии, несколько одновременно
запущенных winws, конфликт с другими обходчиками DPI, пустые списки.

Правила детерминированы и работают без сети — слой ИИ подключается поверх и
только дополняет этот результат, но не заменяет его.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from app.core import service, winws
from app.core.diagnostics.collectors import SystemFacts, disable_proxy
from app.core.probe import http

log = logging.getLogger(__name__)


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    OK = "ok"


SEVERITY_LABELS: dict[Severity, str] = {
    Severity.ERROR: "Проблема",
    Severity.WARNING: "Стоит проверить",
    Severity.INFO: "К сведению",
    Severity.OK: "В порядке",
}

_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2, Severity.OK: 3}


@dataclass(frozen=True)
class Finding:
    """Одна находка диагностики."""

    id: str
    severity: Severity
    title: str
    detail: str = ""
    fix: str = ""
    fix_label: str = ""
    link: str = ""

    @property
    def is_problem(self) -> bool:
        return self.severity in (Severity.ERROR, Severity.WARNING)


# --- починки по кнопке --------------------------------------------------

FIXES: dict[str, Callable[[], bool]] = {
    "enable_tcp_timestamps": service.enable_tcp_timestamps,
    "disable_proxy": disable_proxy,
    "stop_extra_winws": lambda: bool(winws.kill_all()),
}


def apply_fix(fix_id: str) -> bool:
    action = FIXES.get(fix_id)
    if action is None:
        return False
    try:
        return bool(action())
    except Exception:  # noqa: BLE001 — починка не должна ронять диагностику
        log.exception("Починка %s завершилась ошибкой", fix_id)
        return False


# --- правила ------------------------------------------------------------


def evaluate(facts: SystemFacts) -> list[Finding]:
    """Прогоняет все правила и возвращает находки, тяжёлые первыми."""
    findings: list[Finding] = []
    for rule in _RULES:
        finding = rule(facts)
        if finding is not None:
            findings.append(finding)

    findings.sort(key=lambda finding: _ORDER[finding.severity])
    return findings


def problems(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.is_problem]


def _rights(facts: SystemFacts) -> Finding:
    if facts.is_admin:
        return Finding("admin", Severity.OK, "Права администратора получены")
    return Finding(
        "admin",
        Severity.ERROR,
        "Нет прав администратора",
        "Без них нельзя управлять службой и загрузить драйвер WinDivert. "
        "Перезапустите приложение от имени администратора.",
    )


def _core(facts: SystemFacts) -> Finding:
    if not facts.core_present:
        return Finding(
            "core",
            Severity.ERROR,
            "Ядро zapret не установлено",
            "Откройте раздел «Обновления» и установите официальную сборку Flowseal.",
        )
    return Finding(
        "core",
        Severity.OK,
        f"Ядро {facts.core_version or 'без версии'}, стратегий: {facts.strategy_count}",
        facts.core_path,
    )


def _bfe(facts: SystemFacts) -> Finding:
    if facts.bfe_running:
        return Finding("bfe", Severity.OK, "Служба Base Filtering Engine работает")
    return Finding(
        "bfe",
        Severity.ERROR,
        "Служба Base Filtering Engine не запущена",
        "Без неё обход не работает в принципе. Запустите службу BFE в services.msc "
        "и переведите её в автоматический запуск.",
    )


def _windivert_driver(facts: SystemFacts) -> Finding | None:
    if not facts.core_present:
        return None
    if facts.windivert_driver_present:
        return Finding("windivert_file", Severity.OK, "Драйвер WinDivert на месте")
    return Finding(
        "windivert_file",
        Severity.ERROR,
        "Файл драйвера WinDivert отсутствует",
        "Чаще всего его удаляет антивирус. Добавьте папку ядра в исключения "
        "и переустановите сборку в разделе «Обновления».",
    )


def _timestamps(facts: SystemFacts) -> Finding:
    if facts.tcp_timestamps:
        return Finding("tcp_timestamps", Severity.OK, "TCP timestamps включены")
    return Finding(
        "tcp_timestamps",
        Severity.WARNING,
        "TCP timestamps выключены",
        "Стратегии с параметром --dpi-desync-fooling=ts без них не работают.",
        fix="enable_tcp_timestamps",
        fix_label="Включить",
    )


def _proxy(facts: SystemFacts) -> Finding:
    if not facts.proxy.enabled:
        return Finding("proxy", Severity.OK, "Системный прокси выключен")
    return Finding(
        "proxy",
        Severity.WARNING,
        f"Включён системный прокси: {facts.proxy.server or 'адрес не указан'}",
        "Если вы им не пользуетесь, выключите — иначе трафик пойдёт мимо обхода.",
        fix="disable_proxy",
        fix_label="Выключить",
    )


def _services(facts: SystemFacts) -> Finding:
    if not facts.conflicting_services:
        return Finding("conflicting_services", Severity.OK, "Конфликтующих служб не найдено")
    return Finding(
        "conflicting_services",
        Severity.ERROR,
        "Найдены конфликтующие службы: " + ", ".join(facts.conflicting_services),
        "Эти программы перехватывают трафик раньше обхода. Их нужно отключить "
        "через services.msc или удалить.",
    )


def _processes(facts: SystemFacts) -> Finding:
    if not facts.conflicting_processes:
        return Finding("conflicting_processes", Severity.OK, "Конфликтующих программ не запущено")
    return Finding(
        "conflicting_processes",
        Severity.ERROR,
        "Запущены конфликтующие программы: " + ", ".join(facts.conflicting_processes),
        "Два обходчика DPI одновременно мешают друг другу. Оставьте один. "
        "Adguard, кроме того, ломает Discord.",
        link="https://github.com/Flowseal/zapret-discord-youtube/issues/417",
    )


def _vpn(facts: SystemFacts) -> Finding | None:
    """Активный туннель важнее всех прочих находок: он подменяет результат."""
    if not facts.active_vpn:
        return None
    return Finding(
        "vpn",
        Severity.WARNING,
        f"Трафик идёт через VPN: {facts.active_vpn}",
        "Пока включён туннель, проверять обход бессмысленно — все проверки измеряют "
        "VPN, а не вашего провайдера, и подбор стратегии выдаст случайного победителя. "
        "Выключите VPN перед проверкой и подбором.",
    )


def _path(facts: SystemFacts) -> Finding | None:
    if not facts.core_present:
        return None
    if facts.path_in_onedrive:
        return Finding(
            "path",
            Severity.ERROR,
            "Ядро лежит внутри папки OneDrive",
            "Синхронизация портит файлы сборки. Перенесите приложение, например в C:\\ZapretXmel.",
        )
    if facts.path_has_cyrillic:
        return Finding(
            "path",
            Severity.WARNING,
            "В пути к ядру есть кириллица",
            "Отдельные сборки winws такой путь не принимают. Если обход не работает, "
            "перенесите приложение в папку с латинским именем.",
        )
    return Finding("path", Severity.OK, "Путь к ядру без кириллицы и вне OneDrive")


def _bypass_state(facts: SystemFacts) -> Finding:
    running = facts.winws_count > 0
    service_running = facts.service_state == "running"

    if running and service_running:
        return Finding(
            "bypass",
            Severity.OK,
            f"Обход работает: служба запущена, стратегия «{facts.service_strategy or '—'}»",
        )
    if running:
        return Finding("bypass", Severity.OK, "Обход работает в режиме обычного процесса")
    if service_running:
        return Finding(
            "bypass",
            Severity.ERROR,
            "Служба запущена, но процесс winws не найден",
            "Скорее всего, winws падает при старте. Посмотрите раздел «Логи» "
            "и проверьте, не удалил ли антивирус файлы ядра.",
        )
    return Finding("bypass", Severity.INFO, "Обход сейчас выключен")


def _windivert_pending(facts: SystemFacts) -> Finding | None:
    if facts.windivert_state != "stop_pending":
        return None
    return Finding(
        "windivert_pending",
        Severity.ERROR,
        "Драйвер WinDivert завис в состоянии остановки",
        "Так бывает при конфликте с другим обходчиком DPI. Помогает перезагрузка.",
    )


def _multiple_instances(facts: SystemFacts) -> Finding | None:
    if facts.winws_count <= 1:
        return None
    return Finding(
        "multiple_winws",
        Severity.WARNING,
        f"Одновременно запущено экземпляров winws: {facts.winws_count}",
        "Несколько обходов на пересекающихся фильтрах мешают друг другу. "
        "Оставьте один, если не настраивали профиль приложения намеренно.",
        fix="stop_extra_winws",
        fix_label="Остановить все",
    )


def _foreign_install(facts: SystemFacts) -> Finding | None:
    """Другая копия zapret на той же машине.

    Служба у сборки Flowseal называется так же, как наша, — это одна и та же
    служба. Поэтому без этого предупреждения человек видит «обход работает» и
    чужое имя стратегии, не понимая, откуда они взялись.
    """
    if not facts.foreign_install:
        return None

    return Finding(
        "foreign_install",
        Severity.WARNING,
        f"Найдена другая установка zapret: {facts.foreign_install}",
        f"Признак: {facts.foreign_source}. Служба у неё и у нас одна и та же, "
        "поэтому состояние на главном экране относится к ней.\n\n"
        "Включение обхода здесь переустановит службу на нашу копию, а запуск "
        "в режиме обычного процесса снимет её winws. Пока вы этого не сделали, "
        "прежняя установка продолжает работать как раньше. Свои списки доменов "
        "из неё можно перенести в разделе «Списки».",
    )


def _strategy_marker(facts: SystemFacts) -> Finding | None:
    if facts.service_state == "not_installed" or not facts.service_strategy:
        return None
    if not facts.core_present:
        return None
    # Службу поставила другая установка, и имя стратегии — из её папки.
    # Жаловаться на пропажу того, чего у нас и не было, незачем: об этом
    # говорит отдельная находка про чужую установку.
    if facts.foreign_install:
        return None

    # Список берётся из снимка, а не с диска: иначе правила перестают быть
    # чистой функцией от фактов и начинают зависеть от того, что сейчас
    # лежит в папке — в тестах и на чужой машине это даёт разные ответы.
    if facts.service_strategy in facts.available_strategies:
        return None

    return Finding(
        "strategy_missing",
        Severity.WARNING,
        f"Служба установлена со стратегией «{facts.service_strategy}», которой больше нет",
        "Такое бывает после обновления ядра, если стратегию переименовали. "
        "Выберите стратегию заново в разделе «Стратегии».",
    )


def _user_lists(facts: SystemFacts) -> Finding | None:
    if not facts.core_present or not facts.user_list_counts:
        return None

    filled = {name: count for name, count in facts.user_list_counts.items() if count > 1}
    if filled:
        detail = ", ".join(f"{name}: {count}" for name, count in filled.items())
        return Finding("user_lists", Severity.OK, "Пользовательские списки заполнены", detail)

    return Finding(
        "user_lists",
        Severity.INFO,
        "Пользовательские списки пусты",
        "Это нормально: штатного списка хватает большинству. Свои домены стоит "
        "добавлять, только если конкретный сайт не открывается.",
    )


def _ipset(facts: SystemFacts) -> Finding | None:
    if not facts.core_present:
        return None
    if facts.ipset_mode == "loaded":
        return Finding("ipset", Severity.OK, "Список IP-адресов загружен")
    if facts.ipset_mode == "any":
        return Finding(
            "ipset",
            Severity.INFO,
            "IP-набор в режиме «любые адреса»",
            "Обход применяется ко всему трафику на отобранных портах. "
            "Это самый широкий режим — хорош для проверки, но нагружает больше.",
        )
    return Finding(
        "ipset",
        Severity.INFO,
        "Фильтр по IP-адресам выключен",
        "Обход работает только по спискам доменов. "
        + ("Список для режима «по списку» скачан." if facts.ipset_has_backup
           else "Чтобы включить режим «по списку», сначала обновите ipset."),
    )


def _curl(_: SystemFacts) -> Finding | None:
    if http.curl_available():
        return None
    return Finding(
        "curl",
        Severity.WARNING,
        "В системе не найден curl.exe",
        "Без него нельзя проверить доступность сайтов и подобрать стратегию. "
        "curl входит в Windows 10 начиная со сборки 1803.",
    )


_RULES: tuple[Callable[[SystemFacts], Finding | None], ...] = (
    _rights,
    _core,
    _bfe,
    _windivert_driver,
    _timestamps,
    _proxy,
    _services,
    _processes,
    _vpn,
    _path,
    _bypass_state,
    _windivert_pending,
    _multiple_instances,
    _foreign_install,
    _strategy_marker,
    _user_lists,
    _ipset,
    _curl,
)
