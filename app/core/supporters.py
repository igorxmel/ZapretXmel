"""Список поддержавших проект.

Список лежит снаружи — в публичном JSON, который правится без пересборки
приложения. Иначе каждое новое имя означало бы новый релиз.

Скачанное кладётся в кэш и показывается, даже когда сети нет: благодарность не
та вещь, которая должна исчезать из-за отвалившегося интернета.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

from app.core import paths

log = logging.getLogger(__name__)

# Адрес по умолчанию. Файл появится в репозитории проекта; до тех пор
# приложение спокойно показывает пустой список и ссылку на Boosty.
DEFAULT_URL = (
    "https://raw.githubusercontent.com/igorxmel/ZapretXmel/main/supporters.json"
)

# Адрес появится позже. Пока он пуст, интерфейс не показывает мёртвую кнопку,
# а честно пишет, что ссылки ещё нет.
BOOSTY_URL = ""

CACHE_NAME = "supporters.json"
TIMEOUT = 15


@dataclass(frozen=True)
class Supporter:
    """Один поддержавший."""

    name: str
    tier: str = ""
    since: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} — {self.tier}" if self.tier else self.name


@dataclass(frozen=True)
class SupportersList:
    """Список и то, откуда он взялся."""

    people: list[Supporter]
    updated: str = ""
    from_cache: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.people


def cache_file() -> Path:
    return paths.data_dir() / CACHE_NAME


def parse(data: object) -> list[Supporter]:
    """Разбирает список.

    Допускаются две формы: массив строк и массив объектов. Первая нужна, чтобы
    список можно было вести вручную, не вспоминая схему.
    """
    if isinstance(data, dict):
        data = data.get("supporters", [])
    if not isinstance(data, list):
        return []

    people: list[Supporter] = []
    for item in data:
        if isinstance(item, str) and item.strip():
            people.append(Supporter(name=item.strip()))
        elif isinstance(item, dict) and str(item.get("name", "")).strip():
            people.append(
                Supporter(
                    name=str(item["name"]).strip(),
                    tier=str(item.get("tier", "")).strip(),
                    since=str(item.get("since", "")).strip(),
                )
            )
    return people


def _read_cache() -> SupportersList:
    path = cache_file()
    if not path.exists():
        return SupportersList(people=[])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SupportersList(people=[])

    return SupportersList(
        people=parse(payload.get("data")),
        updated=str(payload.get("updated", "")),
        from_cache=True,
    )


def _write_cache(data: object) -> None:
    paths.ensure_dirs()
    cache_file().write_text(
        json.dumps(
            {"updated": datetime.now().isoformat(timespec="seconds"), "data": data},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def fetch(url: str = DEFAULT_URL) -> SupportersList:
    """Скачивает список; при неудаче возвращает сохранённый ранее."""
    try:
        response = requests.get(url, timeout=TIMEOUT, headers={"Cache-Control": "no-cache"})
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        log.info("Список поддержавших не скачался (%s), беру сохранённый", error)
        return _read_cache()

    people = parse(data)
    _write_cache(data)
    return SupportersList(
        people=people, updated=datetime.now().strftime("%d.%m.%Y"), from_cache=False
    )


def cached() -> SupportersList:
    """Сохранённый список — чтобы показать что-то сразу, не дожидаясь сети."""
    return _read_cache()
