"""Сведения об установленной копии ядра zapret.

Версию приходится определять по двум источникам: современные сборки пишут её в
`service.bat` (`set "LOCAL_VERSION=..."`), а старые — в `version.txt`, который
создаётся уже во время работы `check_updates.bat`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core import paths, strategies

_LOCAL_VERSION_RE = re.compile(r'set\s+"?LOCAL_VERSION=([^"\r\n]+)"?', re.IGNORECASE)
_VERSION_TXT_RE = re.compile(r"^\s*ver:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class CoreInfo:
    """Состояние папки `core/`."""

    present: bool
    version: str
    strategy_count: int
    path: Path

    @property
    def version_label(self) -> str:
        if not self.present:
            return "ядро не установлено"
        return self.version or "версия неизвестна"


@lru_cache(maxsize=8)
def _version_from_service_bat(path: str, mtime: float, size: int) -> str:  # noqa: ARG001
    """Читает версию из service.bat с кэшем по времени правки.

    Файл весит под сорок килобайт, а состояние опрашивается каждые несколько
    секунд — перечитывать его каждый раз незачем. Ключ кэша включает mtime и
    размер, поэтому после обновления ядра версия подхватится сама.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    match = _LOCAL_VERSION_RE.search(text)
    return match.group(1).strip() if match else ""


def read_version(root: Path | None = None) -> str:
    root = root or paths.core_dir()

    service_bat = root / "service.bat"
    if service_bat.exists():
        stat = service_bat.stat()
        if version := _version_from_service_bat(str(service_bat), stat.st_mtime, stat.st_size):
            return version

    version_txt = root / "version.txt"
    if version_txt.exists():
        text = version_txt.read_text(encoding="utf-8", errors="replace")
        if match := _VERSION_TXT_RE.search(text):
            return match.group(1).strip()

    return ""


def is_present(root: Path | None = None) -> bool:
    """Ядро считается установленным, когда на месте winws и хотя бы одна стратегия."""
    root = root or paths.core_dir()
    return (root / "bin" / "winws.exe").exists() and bool(strategies.discover(root))


def describe(root: Path | None = None) -> CoreInfo:
    root = root or paths.core_dir()
    return CoreInfo(
        present=is_present(root),
        version=read_version(root),
        strategy_count=len(strategies.discover(root)),
        path=root,
    )
