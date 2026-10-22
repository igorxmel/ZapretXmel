"""Каким сообщением просить дочерний процесс закрыться.

Значок tg-ws-proxy держится на pystray. Её окно глотает WM_CLOSE — диспетчер
не знает такого обработчика и возвращает ноль, — поэтому прежняя «просьба
закрыться» ничего не делала, процесс снимали силой, и значок оставался в трее
фантомом. Свой цикл сообщений pystray завершает по WM_USER + 10 и сама
вызывает Shell_NotifyIcon(NIM_DELETE).
"""

from __future__ import annotations

from app.core.process import _WM_CLOSE, _WM_TRAY_STOP, _close_message


def test_tray_window_is_asked_the_way_pystray_understands() -> None:
    """Имя класса pystray составляет сама: <имя><номер>SystemTrayIcon."""
    assert _close_message("TgWsProxy140234SystemTrayIcon") == _WM_TRAY_STOP


def test_ordinary_window_is_closed_normally() -> None:
    assert _close_message("Notepad") == _WM_CLOSE


def test_empty_class_name_falls_back_to_close() -> None:
    assert _close_message("") == _WM_CLOSE


def test_tray_message_matches_the_library() -> None:
    """Значение взято из pystray._util.win32; менять его нельзя."""
    assert _WM_TRAY_STOP == 0x0400 + 10
