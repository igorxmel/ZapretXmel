"""Пауза обхода, пока трафик идёт через VPN.

winws перехватывает пакеты на всех адаптерах, в том числе на туннельном. Сайты
и приложения из его списков он обрабатывает и внутри туннеля, и именно они
перестают работать через VPN: YouTube не грузится, Discord отваливается через
минуту. Остальной трафик VPN идёт как обычно. Пока туннель включён, обход всё
равно ничего не даёт — всё уходит через VPN, — поэтому его проще выключить.

Здесь только решение «поставить на паузу, снять или ничего». Само выключение и
включение делает контроллер.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Сколько опросов подряд туннель должен быть виден (или не виден), прежде чем
# что-то делать. Опрос раз в три секунды: при переподключении VPN адаптер
# пропадает на секунду-другую, и обход не должен дёргаться от каждого такого раза.
CONFIRM = 2

PAUSE = "pause"
RESUME = "resume"

# Какой VPN ждать (`Settings.vpn_target`). Пусто — любой туннель, через который
# идёт трафик. Остальное — то, что человек выбрал сам, когда автоопределение
# промахивается: туннель назван нейтрально или нужно реагировать на программу.
ADAPTER = "adapter:"
APP = "app:"

# Адаптеры, которые туннелем не бывают: выбирать их незачем.
_NOT_TUNNELS = ("loopback", "teredo", "isatap", "bluetooth")


def adapter_up(name: str) -> bool:
    """Поднят ли адаптер. Туннель Wintun и TAP «подключён» только при живом VPN."""
    import psutil

    stats = psutil.net_if_stats().get(name)
    return bool(stats and stats.isup)


def app_running(path: str) -> bool:
    from app.core import appwatch

    return appwatch.is_running(path, appwatch.running_executables([path]))


def trigger(target: str, detected: str) -> str:
    """Имя VPN, из-за которого нужна пауза, или пусто.

    `detected` — туннель, найденный автоматически: им и отвечаем, если человек
    ничего не выбирал.
    """
    if target.startswith(ADAPTER):
        name = target[len(ADAPTER):]
        return name if name and adapter_up(name) else ""
    if target.startswith(APP):
        path = target[len(APP):]
        return Path(path).stem if path and app_running(path) else ""
    return detected


def adapters() -> list[str]:
    """Сетевые адаптеры для выбора: похожие на туннель первыми."""
    import psutil

    from app.core.diagnostics import vpn

    names = [
        name
        for name in psutil.net_if_stats()
        if not any(word in name.lower() for word in _NOT_TUNNELS)
    ]
    return sorted(names, key=lambda name: (not vpn.looks_like_tunnel(name), name.lower()))


def label(target: str) -> str:
    """Как выбор называется в списке."""
    if target.startswith(ADAPTER):
        return f"Адаптер «{target[len(ADAPTER):]}»"
    if target.startswith(APP):
        return f"Программа «{Path(target[len(APP):]).name}»"
    return "Любой VPN — найти автоматически"


@dataclass
class Tracker:
    """Что видели на прошлых опросах."""

    seen: int = 0
    gone: int = 0

    def observe(self, tunnel: str) -> None:
        if tunnel:
            self.seen += 1
            self.gone = 0
        else:
            self.gone += 1
            self.seen = 0


def decide(
    tracker: Tracker,
    tunnel: str,
    *,
    enabled: bool,
    active: bool,
    paused: bool,
    busy: bool,
) -> str:
    """PAUSE, RESUME или пустая строка. Счётчики `tracker` обновляет сама."""
    tracker.observe(tunnel)
    if busy:
        return ""

    if paused:
        # Галочку сняли во время паузы — человек хочет обход обратно.
        if not enabled or tracker.gone >= CONFIRM:
            return RESUME
        return ""

    # Исключения «включил руками при VPN» нет: с галочкой обход при VPN не
    # работает никогда. Кому он нужен вместе с VPN, снимает галочку.
    if enabled and active and tunnel and tracker.seen >= CONFIRM:
        return PAUSE
    return ""
