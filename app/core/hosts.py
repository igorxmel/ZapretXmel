"""Управляемая секция системного файла hosts.

Апстрим скачивает свой hosts и просит перенести содержимое руками. Здесь это
делается за пользователя, но аккуратно: наши строки живут между маркерами,
всё остальное содержимое файла не трогается, а перед каждой записью
сохраняется резервная копия.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

from app.core import paths

log = logging.getLogger(__name__)

BEGIN_MARKER = "# >>> ZapretXmel: начало управляемой секции"
END_MARKER = "# <<< ZapretXmel: конец управляемой секции"

HOSTS_URL = (
    "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube"
    "/refs/heads/main/.service/hosts"
)

CREATE_NO_WINDOW = 0x08000000


def hosts_path() -> Path:
    root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return Path(root) / "System32" / "drivers" / "etc" / "hosts"


@dataclass(frozen=True)
class HostsStatus:
    exists: bool
    managed: bool
    managed_lines: int
    total_lines: int


def _read() -> str:
    path = hosts_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def status() -> HostsStatus:
    content = _read()
    if not content:
        return HostsStatus(exists=False, managed=False, managed_lines=0, total_lines=0)

    managed = _extract_section(content)
    return HostsStatus(
        exists=True,
        managed=managed is not None,
        managed_lines=len([line for line in (managed or "").splitlines() if line.strip()]),
        total_lines=len(content.splitlines()),
    )


def _extract_section(content: str) -> str | None:
    if BEGIN_MARKER not in content or END_MARKER not in content:
        return None
    _, _, rest = content.partition(BEGIN_MARKER)
    section, _, _ = rest.partition(END_MARKER)
    return section.strip("\n")


def _strip_section(content: str) -> str:
    if BEGIN_MARKER not in content:
        return content
    head, _, rest = content.partition(BEGIN_MARKER)
    _, _, tail = rest.partition(END_MARKER)
    return head.rstrip("\n") + "\n" + tail.lstrip("\n")


def fetch_upstream(timeout: int = 20) -> str:
    """Скачивает hosts из репозитория Flowseal."""
    response = requests.get(
        HOSTS_URL, timeout=timeout, headers={"Cache-Control": "no-cache"}
    )
    response.raise_for_status()
    return response.text


def backup() -> Path:
    """Сохраняет текущий hosts перед изменением."""
    paths.backups_dir().mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = paths.backups_dir() / f"hosts-{stamp}.txt"
    target.write_text(_read(), encoding="utf-8")
    return target


def apply(section: str) -> int:
    """Записывает управляемую секцию, оставляя остальной файл нетронутым.

    Возвращает число добавленных строк.
    """
    backup()
    current = _strip_section(_read()).rstrip("\n")

    lines = [line for line in section.splitlines() if line.strip()]
    block = "\n".join([BEGIN_MARKER, *lines, END_MARKER])
    updated = f"{current}\n\n{block}\n" if current else f"{block}\n"

    hosts_path().write_text(updated, encoding="utf-8")
    flush_dns()
    log.info("В hosts записано строк: %d", len(lines))
    return len(lines)


def remove() -> bool:
    """Убирает управляемую секцию, не трогая чужие записи."""
    content = _read()
    if BEGIN_MARKER not in content:
        return False

    backup()
    hosts_path().write_text(_strip_section(content), encoding="utf-8")
    flush_dns()
    return True


def flush_dns() -> None:
    """Сбрасывает кэш DNS — без этого правки в hosts применятся не сразу."""
    try:
        subprocess.run(  # noqa: S603 — системная утилита с фиксированными аргументами
            ["ipconfig", "/flushdns"],
            capture_output=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.warning("Не удалось сбросить кэш DNS")
