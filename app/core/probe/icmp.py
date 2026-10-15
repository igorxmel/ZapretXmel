"""ICMP-пинг через iphlpapi.

Вызов `ping.exe` пришлось бы разбирать по локализованному выводу, поэтому
обращаемся к API напрямую: результат не зависит от языка системы и приходит
быстрее — лишний процесс на каждую цель при переборе стратегий заметен.
"""

from __future__ import annotations

import contextlib
import ctypes
import functools
import logging
import socket
from ctypes import wintypes

log = logging.getLogger(__name__)

_IP_SUCCESS = 0
_PAYLOAD = b"zapretxmel-probe"


class _IcmpEchoReply(ctypes.Structure):
    _fields_ = [
        ("Address", wintypes.ULONG),
        ("Status", wintypes.ULONG),
        ("RoundTripTime", wintypes.ULONG),
        ("DataSize", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("Data", ctypes.c_void_p),
        ("Options", ctypes.c_byte * 8),
    ]


@functools.cache
def _icmp_api() -> ctypes.WinDLL | None:
    """Готовит iphlpapi с объявленными типами.

    Без явных argtypes/restype ctypes считает, что функции возвращают 32-битный
    int, и в 64-битном процессе хэндл от IcmpCreateFile обрезается — пинг молча
    перестаёт работать.
    """
    try:
        library = ctypes.WinDLL("iphlpapi.dll")
    except OSError:
        log.debug("iphlpapi недоступна")
        return None

    library.IcmpCreateFile.restype = wintypes.HANDLE
    library.IcmpCreateFile.argtypes = []

    library.IcmpCloseHandle.restype = wintypes.BOOL
    library.IcmpCloseHandle.argtypes = [wintypes.HANDLE]

    library.IcmpSendEcho.restype = wintypes.DWORD
    library.IcmpSendEcho.argtypes = [
        wintypes.HANDLE,  # IcmpHandle
        wintypes.ULONG,  # DestinationAddress
        wintypes.LPVOID,  # RequestData
        wintypes.WORD,  # RequestSize
        wintypes.LPVOID,  # RequestOptions
        wintypes.LPVOID,  # ReplyBuffer
        wintypes.DWORD,  # ReplySize
        wintypes.DWORD,  # Timeout
    ]
    return library


def _resolve(host: str) -> str | None:
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


def ping(host: str, timeout_ms: int = 1000) -> float | None:
    """Возвращает время отклика в миллисекундах или None, если ответа нет."""
    address = _resolve(host)
    if address is None:
        return None

    iphlpapi = _icmp_api()
    if iphlpapi is None:
        return None

    handle = iphlpapi.IcmpCreateFile()
    if not handle or handle == wintypes.HANDLE(-1).value:
        return None

    try:
        destination = ctypes.c_uint32.from_buffer_copy(socket.inet_aton(address)).value

        request = ctypes.create_string_buffer(_PAYLOAD, len(_PAYLOAD))
        buffer_size = ctypes.sizeof(_IcmpEchoReply) + len(_PAYLOAD) + 8
        reply_buffer = ctypes.create_string_buffer(buffer_size)

        replies = iphlpapi.IcmpSendEcho(
            handle,
            destination,
            ctypes.cast(request, wintypes.LPVOID),
            len(_PAYLOAD),
            None,
            ctypes.cast(reply_buffer, wintypes.LPVOID),
            buffer_size,
            timeout_ms,
        )
        if replies == 0:
            return None

        reply = ctypes.cast(reply_buffer, ctypes.POINTER(_IcmpEchoReply)).contents
        if reply.Status != _IP_SUCCESS:
            return None
        return float(reply.RoundTripTime)
    except (OSError, ValueError):
        return None
    finally:
        with contextlib.suppress(OSError):
            iphlpapi.IcmpCloseHandle(handle)
