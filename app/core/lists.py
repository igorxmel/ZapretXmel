"""Пользовательские списки доменов и адресов.

Апстрим держит рядом два набора файлов: свои (перезаписываются при обновлении)
и пользовательские с суффиксом `-user` (не трогаются никогда). Редактируем
только вторые — тогда обновление ядра не затирает правки.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core import paths

log = logging.getLogger(__name__)

Kind = Literal["domain", "ip"]

# Заглушки, которыми service.bat наполняет пустые пользовательские файлы:
# winws не любит пустые списки, поэтому там всегда есть хотя бы одна строка.
PLACEHOLDER_DOMAIN = "domain.example.abc"
PLACEHOLDER_IP = "203.0.113.113/32"

_DOMAIN_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$"
)


@dataclass(frozen=True)
class UserList:
    """Описание редактируемого списка."""

    filename: str
    kind: Kind
    title: str
    hint: str

    @property
    def path(self) -> Path:
        return paths.core_lists() / self.filename

    @property
    def placeholder(self) -> str:
        return PLACEHOLDER_DOMAIN if self.kind == "domain" else PLACEHOLDER_IP


USER_LISTS: tuple[UserList, ...] = (
    UserList(
        filename="list-general-user.txt",
        kind="domain",
        title="Свои домены",
        hint="Сайты, которые нужно пропускать через обход дополнительно к штатному списку.",
    ),
    UserList(
        filename="list-exclude-user.txt",
        kind="domain",
        title="Домены-исключения",
        hint="Сайты, которые обход трогать не должен — помогает, когда страница ломается.",
    ),
    UserList(
        filename="ipset-exclude-user.txt",
        kind="ip",
        title="Адреса-исключения",
        hint="IP-адреса и подсети (CIDR), которые нужно обойти стороной.",
    ),
)


def ensure_user_lists() -> None:
    """Создаёт недостающие пользовательские файлы — так же, как `service.bat`."""
    directory = paths.core_lists()
    if not directory.is_dir():
        return

    for user_list in USER_LISTS:
        if user_list.path.exists():
            continue
        header = "# Этот файл не затирается при обновлении ядра\n"
        user_list.path.write_text(f"{header}{user_list.placeholder}\n", encoding="utf-8")


def is_valid_domain(value: str) -> bool:
    if not value or len(value) > 253 or ".." in value:
        return False
    return bool(_DOMAIN_RE.match(value))


def is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False
    return True


def validate(value: str, kind: Kind) -> bool:
    return is_valid_domain(value) if kind == "domain" else is_valid_ip(value)


@dataclass(frozen=True)
class ListContent:
    """Разобранное содержимое списка: записи, комментарии и ошибки."""

    entries: list[str]
    comments: list[str]
    invalid: list[str]


def read(user_list: UserList) -> ListContent:
    """Читает список, отделяя комментарии и некорректные строки."""
    if not user_list.path.exists():
        return ListContent([], [], [])

    entries: list[str] = []
    comments: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for raw_line in user_list.path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            comments.append(line)
            continue
        normalized = line.lower()
        if normalized in seen:
            continue
        if validate(line, user_list.kind):
            seen.add(normalized)
            entries.append(line)
        else:
            invalid.append(line)

    return ListContent(entries, comments, invalid)


def write(user_list: UserList, entries: list[str], comments: list[str] | None = None) -> int:
    """Сохраняет список: дубликаты убираются, записи сортируются.

    Пустой список недопустим — winws на нём ругается, поэтому вместо пустоты
    записывается заглушка, как это делает апстрим.
    """
    unique: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        value = entry.strip()
        if not value or value.lower() in seen:
            continue
        if not validate(value, user_list.kind):
            continue
        seen.add(value.lower())
        unique.append(value)

    unique.sort(key=str.lower)
    if not unique:
        unique = [user_list.placeholder]

    lines = list(comments or [])
    lines.extend(unique)

    user_list.path.parent.mkdir(parents=True, exist_ok=True)
    user_list.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(unique)


def import_from(source_root: Path) -> dict[str, int]:
    """Переносит пользовательские списки из другой установки zapret.

    Записи добавляются к текущим, а не заменяют их: при переезде со старой
    сборки терять уже накопленное не хочется.
    """
    imported: dict[str, int] = {}
    candidates = [source_root, source_root / "lists"]

    for user_list in USER_LISTS:
        source = next(
            (folder / user_list.filename for folder in candidates
             if (folder / user_list.filename).exists()),
            None,
        )
        if source is None:
            continue

        incoming = [
            line.strip()
            for line in source.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        incoming = [
            value
            for value in incoming
            if validate(value, user_list.kind) and value != user_list.placeholder
        ]
        if not incoming:
            continue

        current = read(user_list)
        merged = current.entries + incoming
        count = write(user_list, merged, current.comments)
        imported[user_list.filename] = count - len(current.entries)
        log.info("Из %s перенесено записей: %d", source, imported[user_list.filename])

    return imported
