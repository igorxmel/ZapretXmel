"""Подмена активных фейковых пакетов.

Стратегии ссылаются на `ACTIVE_DISCORD_UDP.bin` и `ACTIVE_GAME_UDP.bin`, а это
просто копии одного из остальных `.bin` в папке `bin/`. Какой именно фейк сейчас
активен, апстрим определяет сравнением SHA-256 — тем же способом пользуемся и мы,
иначе пришлось бы хранить состояние отдельно и рассинхронизироваться с
консольным меню.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core import paths

log = logging.getLogger(__name__)

ACTIVE_SLOTS: dict[str, str] = {
    "ACTIVE_DISCORD_UDP.bin": "Discord UDP",
    "ACTIVE_GAME_UDP.bin": "Игровой фильтр UDP",
}


@dataclass(frozen=True)
class Slot:
    """Активный фейк и имя файла, из которого он скопирован."""

    filename: str
    title: str
    current: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def available(bin_dir: Path | None = None) -> list[Path]:
    """Фейковые пакеты, которые можно назначить активными."""
    bin_dir = bin_dir or paths.core_bin()
    if not bin_dir.is_dir():
        return []
    return sorted(
        path for path in bin_dir.glob("*.bin") if not path.name.startswith("ACTIVE_")
    )


def slots(bin_dir: Path | None = None) -> list[Slot]:
    """Текущее состояние активных слотов."""
    bin_dir = bin_dir or paths.core_bin()
    candidates = {path: _sha256(path) for path in available(bin_dir)}

    result: list[Slot] = []
    for filename, title in ACTIVE_SLOTS.items():
        active = bin_dir / filename
        current = ""
        if active.exists():
            active_hash = _sha256(active)
            current = next(
                (path.stem for path, digest in candidates.items() if digest == active_hash),
                "неизвестный файл",
            )
        result.append(Slot(filename=filename, title=title, current=current))

    return result


def replace(slot_filename: str, source_name: str, bin_dir: Path | None = None) -> None:
    """Назначает активным фейком указанный файл."""
    bin_dir = bin_dir or paths.core_bin()
    source = bin_dir / f"{source_name}.bin"
    if not source.exists():
        raise FileNotFoundError(f"нет файла {source.name}")
    if slot_filename not in ACTIVE_SLOTS:
        raise ValueError(f"неизвестный слот {slot_filename}")

    shutil.copyfile(source, bin_dir / slot_filename)
    log.info("Активный фейк %s заменён на %s", slot_filename, source.name)
