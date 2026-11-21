"""Проверка локального каталога оболочек и целостности пакетов."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

API_VERSION = 1
MIME = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".png": "image/png",
    ".webp": "image/webp",
}
MAX_BYTES = 2 * 1024 * 1024
PACKAGE_ID = re.compile(r"[a-z][a-z0-9-]{0,47}")
FILE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\.[a-z]{2,5}")
SHA256 = re.compile(r"[0-9a-f]{64}")


class PackageError(ValueError):
    """Каталог или пакет не прошёл проверку."""


def read_file(directory: Path, name: str, limit: int = MAX_BYTES) -> bytes:
    path = directory / name
    try:
        if path.resolve().parent != directory.resolve():
            raise PackageError(f"Файл выходит за пределы пакета: {name}.")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as error:
        raise PackageError(f"Не удалось прочитать {name}.") from error
    if len(data) > limit:
        raise PackageError(f"Файл слишком большой: {name}.")
    return data


def parse_json(data: bytes) -> dict:
    try:
        value = json.loads(data)
    except ValueError as error:
        raise PackageError("Некорректный JSON.") from error
    if not isinstance(value, dict):
        raise PackageError("Ожидался JSON-объект.")
    return value


def verify(data: bytes, expected: object, name: str) -> None:
    if not isinstance(expected, str) or not SHA256.fullmatch(expected):
        raise PackageError(f"Некорректная контрольная сумма: {name}.")
    if hashlib.sha256(data).hexdigest() != expected:
        raise PackageError(f"Контрольная сумма не совпала: {name}.")


def load_catalog(root: Path) -> dict[str, str]:
    index = parse_json(read_file(root, "catalog.json", 64 * 1024))
    entries = index.get("packages")
    if type(index.get("schema")) is not int or index["schema"] != 1:
        raise PackageError("Версия каталога не поддерживается.")
    if not isinstance(entries, dict):
        raise PackageError("Ожидался список пакетов в поле packages.")
    for name, checksum in entries.items():
        if not PACKAGE_ID.fullmatch(name):
            raise PackageError("Недопустимый идентификатор оболочки.")
        if not isinstance(checksum, str) or not SHA256.fullmatch(checksum):
            raise PackageError(f"Некорректная контрольная сумма манифеста: {name}.")
    return entries


def load_package(root: Path, name: str) -> dict[str, tuple[str, bytes]]:
    entries = load_catalog(root)
    if name not in entries:
        raise PackageError(f"Оболочка «{name}» отсутствует в каталоге.")
    directory = root / name
    if directory.resolve().parent != root.resolve():
        raise PackageError("Папка оболочки выходит за пределы каталога.")
    raw = read_file(directory, "manifest.json", 64 * 1024)
    verify(raw, entries[name], "manifest.json")
    manifest = parse_json(raw)
    if manifest.get("id") != name:
        raise PackageError("Идентификатор оболочки не совпадает с каталогом.")
    if type(manifest.get("api")) is not int or manifest["api"] != API_VERSION:
        raise PackageError("Версия API оболочки не поддерживается.")
    for field in ("title", "version"):
        value = manifest.get(field)
        if not isinstance(value, str) or not 0 < len(value.strip()) <= 80:
            raise PackageError(f"Укажите поле {field} в манифесте.")
    files = manifest.get("files")
    if not isinstance(files, dict) or "index.html" not in files or len(files) > 40:
        raise PackageError("Пакет должен содержать index.html и не более 40 файлов.")
    routes = {}
    remaining = MAX_BYTES
    for file, checksum in files.items():
        mime = MIME.get(Path(file).suffix)
        if not FILE_NAME.fullmatch(file) or mime is None:
            raise PackageError("Имя или тип файла пакета не поддерживается.")
        data = read_file(directory, file, remaining)
        verify(data, checksum, file)
        remaining -= len(data)
        routes["/" + file] = (mime, data)
    routes["/"] = routes["/index.html"]
    return routes
