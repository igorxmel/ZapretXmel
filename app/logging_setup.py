"""Настройка журналирования."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.core import paths

FORMAT = "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 3


def setup(level: int = logging.INFO) -> None:
    """Пишет лог в файл с ротацией и, если есть консоль, дублирует в неё."""
    paths.ensure_dirs()

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter(FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = RotatingFileHandler(
        paths.logs_dir() / "app.log",
        maxBytes=MAX_BYTES,
        backupCount=BACKUPS,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # В сборке без консоли stderr отсутствует — тогда обработчик не нужен.
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
