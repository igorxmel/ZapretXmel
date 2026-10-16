"""Достаёт описание версии из CHANGELOG.md.

Автоматические заметки GitHub — это перечень коммитов: они написаны для того,
кто правит код, а не для того, кто программой пользуется. Поэтому описание
релиза берётся из `CHANGELOG.md`, где оно написано словами.

    python tools/release_notes.py 0.1.6          # напечатать раздел
    python tools/release_notes.py 0.1.6 -o notes.md

Если раздела нет, скрипт падает: лучше заметить это на сборке, чем выложить
релиз без описания.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

CHANGELOG = ROOT / "CHANGELOG.md"


# Разбор один на всех: программа показывает тот же раздел в окне
# «что нового», и расходиться им незачем.
from app.core.changelog import section  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Описание релиза из CHANGELOG.md")
    parser.add_argument("version", help="номер версии, например 0.1.6")
    parser.add_argument("-o", "--output", type=Path, help="записать в файл")
    arguments = parser.parse_args()

    version = arguments.version.lstrip("v")
    if not CHANGELOG.exists():
        raise SystemExit(f"нет файла {CHANGELOG}")

    notes = section(CHANGELOG.read_text(encoding="utf-8"), version)
    if not notes:
        raise SystemExit(
            f"в CHANGELOG.md нет раздела про {version} — "
            "опишите изменения перед выпуском"
        )

    if arguments.output:
        arguments.output.write_text(notes + "\n", encoding="utf-8")
        print(f"описание сохранено: {arguments.output}")
    else:
        print(notes)

    return 0


if __name__ == "__main__":
    sys.exit(main())
