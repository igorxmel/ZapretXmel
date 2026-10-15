"""Хранение ключей доступа к нейросетям.

Ключи шифруются средствами Windows (DPAPI) и привязываются к учётной записи:
расшифровать их сможет только тот же пользователь на этой же машине. Класть
их в обычный конфиг нельзя — он лежит рядом с программой и попадает в бэкапы,
архивы и диагностические пакеты.
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
from ctypes import wintypes
from pathlib import Path

from app.core import paths

log = logging.getLogger(__name__)

STORE_NAME = "secrets.json"
ENTROPY = b"ZapretXmel.secrets.v1"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _to_blob(data: bytes) -> _Blob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _from_blob(blob: _Blob) -> bytes:
    size = int(blob.cbData)
    return ctypes.string_at(blob.pbData, size) if size else b""


def _free(blob: _Blob) -> None:
    if blob.pbData:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def encrypt(value: str) -> str:
    """Шифрует строку и возвращает её в виде base64."""
    source = _to_blob(value.encode("utf-8"))
    entropy = _to_blob(ENTROPY)
    result = _Blob()

    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0, ctypes.byref(result)
    )
    if not ok:
        raise OSError("не удалось зашифровать значение средствами Windows")

    try:
        return base64.b64encode(_from_blob(result)).decode("ascii")
    finally:
        _free(result)


def decrypt(value: str) -> str:
    """Расшифровывает строку, зашифрованную на этой же учётной записи."""
    source = _to_blob(base64.b64decode(value))
    entropy = _to_blob(ENTROPY)
    result = _Blob()

    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0, ctypes.byref(result)
    )
    if not ok:
        raise OSError("не удалось расшифровать значение — оно от другой учётной записи")

    try:
        return _from_blob(result).decode("utf-8")
    finally:
        _free(result)


def store_file() -> Path:
    return paths.data_dir() / STORE_NAME


def _read_store() -> dict[str, str]:
    path = store_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Хранилище ключей повреждено, начинаю с пустого")
        return {}
    return data if isinstance(data, dict) else {}


def _write_store(store: dict[str, str]) -> None:
    paths.ensure_dirs()
    store_file().write_text(json.dumps(store, indent=2), encoding="utf-8")


def save(name: str, value: str) -> None:
    """Сохраняет ключ. Пустое значение удаляет запись."""
    store = _read_store()
    if not value:
        store.pop(name, None)
    else:
        store[name] = encrypt(value)
    _write_store(store)


def load(name: str) -> str:
    """Возвращает ключ или пустую строку, если его нет или он не читается."""
    encrypted = _read_store().get(name)
    if not encrypted:
        return ""
    try:
        return decrypt(encrypted)
    except (OSError, ValueError):
        log.warning("Ключ %s не расшифровывается — вероятно, он от другой учётной записи", name)
        return ""


def has(name: str) -> bool:
    return bool(load(name))


def forget(name: str) -> None:
    save(name, "")
