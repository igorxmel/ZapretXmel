"""Каталог списков сообщества — ветка `community-lists` этого же репозитория.

Своего сервера у проекта нет и не будет: каталог — это `index.json` и файлы в
отдельной ветке, а новые списки приходят pull request'ами, которые проверяет
`tools/check_catalog.py` той ветки и просматривает автор. Программа только читает.

Список — данные, а не код: домены по одному на строку. Здесь они ещё раз проходят
ту же проверку, что и записи, введённые руками, и попадают сначала в редактор —
сохраняет человек сам.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import requests

from app.core import lists
from app.core.updater.github import USER_AGENT, describe

log = logging.getLogger(__name__)

BRANCH = "community-lists"
BASE_URL = f"https://raw.githubusercontent.com/igorxmel/ZapretXmel/{BRANCH}"
BROWSE_URL = f"https://github.com/igorxmel/ZapretXmel/tree/{BRANCH}"
TIMEOUT = 15

Kind = Literal["domain", "exclude"]

# В какой свой список попадает список каждого вида.
TARGET_FILE: dict[str, str] = {
    "domain": "list-general-user.txt",
    "exclude": "list-exclude-user.txt",
}


class CatalogError(Exception):
    """Каталог не получен или не разобран."""


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    description: str
    author: str
    kind: Kind
    file: str

    @property
    def target(self) -> lists.UserList:
        name = TARGET_FILE[self.kind]
        return next(item for item in lists.USER_LISTS if item.filename == name)

    @property
    def kind_label(self) -> str:
        return "для обхода" if self.kind == "domain" else "исключения"


def _get(path: str) -> requests.Response:
    try:
        response = requests.get(
            f"{BASE_URL}/{path}", timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise CatalogError(describe(error)) from error
    return response


def catalog() -> list[Entry]:
    """Списки из каталога. Неполные и непонятные записи пропускаются, а не ломают всё."""
    try:
        data = _get("index.json").json()
    except ValueError as error:
        raise CatalogError("каталог пришёл повреждённым") from error

    entries: list[Entry] = []
    for item in data.get("lists", []) if isinstance(data, dict) else []:
        try:
            entry = Entry(**{key: str(item[key]) for key in Entry.__dataclass_fields__})
        except (KeyError, TypeError):
            log.info("Запись каталога пропущена: %s", item)
            continue
        if entry.kind in TARGET_FILE and entry.file.startswith("lists/"):
            entries.append(entry)
    return entries


def fetch(entry: Entry) -> tuple[list[str], list[str]]:
    """Домены списка: годные и отброшенные — та же проверка, что у импорта из файла."""
    return lists.parse_import(_get(entry.file).text, "domain")
