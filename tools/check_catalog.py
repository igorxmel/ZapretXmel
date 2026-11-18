"""Проверка каталога списков: запускается в pull request'ах в ветку community-lists.

Без зависимостей: только стандартная библиотека, чтобы проверка не зависела от того,
что лежит в репозитории программы.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$")
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# domain — сайты для обхода, exclude — сайты, которые обход трогать не должен.
KINDS = ("domain", "exclude")
FIELDS = ("id", "title", "description", "author", "kind", "file")
MAX_ENTRIES = 5000


def valid(value: str) -> bool:
    return len(value) <= 253 and bool(DOMAIN.match(value))


def check() -> list[str]:
    errors: list[str] = []
    data = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    seen: set[str] = set()
    for number, item in enumerate(data.get("lists", []), start=1):
        where = f"index.json, список №{number}"
        missing = [name for name in FIELDS if not str(item.get(name, "")).strip()]
        if missing:
            errors.append(f"{where}: не заполнено {', '.join(missing)}")
            continue
        if not ID.match(item["id"]):
            errors.append(f"{where}: id только из латиницы, цифр и дефисов")
        if item["id"] in seen:
            errors.append(f"{where}: id {item['id']} уже есть")
        seen.add(item["id"])
        if item["kind"] not in KINDS:
            errors.append(f"{where}: kind — domain или exclude")
            continue
        if item["file"] != f"lists/{item['id']}.txt":
            errors.append(f"{where}: файл должен называться lists/{item['id']}.txt")
            continue
        path = ROOT / item["file"]
        if not path.is_file():
            errors.append(f"{where}: нет файла {item['file']}")
            continue
        entries = [
            line.split("#", 1)[0].strip()
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        entries = [line for line in entries if line]
        bad = [line for line in entries if not valid(line)]
        if bad:
            errors.append(f"{item['file']}: не подходит: {', '.join(bad[:5])}")
        if not entries:
            errors.append(f"{item['file']}: пустой список")
        if len(entries) > MAX_ENTRIES:
            errors.append(f"{item['file']}: больше {MAX_ENTRIES} записей — разбейте по назначению")

    listed = {item.get("file") for item in data.get("lists", [])}
    for path in (ROOT / "lists").glob("*.txt"):
        if f"lists/{path.name}" not in listed:
            errors.append(f"lists/{path.name}: нет в index.json")
    return errors


if __name__ == "__main__":
    problems = check()
    for problem in problems:
        print(f"::error::{problem}")
    print("Каталог в порядке" if not problems else f"Ошибок: {len(problems)}")
    sys.exit(1 if problems else 0)
