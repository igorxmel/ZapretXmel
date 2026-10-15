"""Цели проверки.

Формат повторяет `utils/targets.txt` из сборки Flowseal, поэтому список можно
править в одном файле и для консольного тестера, и для нашего авто-подбора:

    DiscordMain       = "https://discord.com"
    CloudflareDNS1111 = "PING:1.1.1.1"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.core import paths

_LINE_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"([^"]+)"\s*$')
_PING_PREFIX = "PING:"


@dataclass(frozen=True)
class Target:
    """Одна проверяемая точка: сайт или адрес для пинга."""

    name: str
    url: str = ""
    ping_host: str = ""
    group: str = ""

    @property
    def is_ping_only(self) -> bool:
        return not self.url

    @property
    def host(self) -> str:
        if self.ping_host:
            return self.ping_host
        return self.url.split("//", 1)[-1].split("/", 1)[0]


# Запасной список на случай, если ядро ещё не установлено.
BUILTIN: tuple[Target, ...] = (
    Target("DiscordMain", url="https://discord.com", group="Discord"),
    Target("DiscordGateway", url="https://gateway.discord.gg", group="Discord"),
    Target("DiscordCDN", url="https://cdn.discordapp.com", group="Discord"),
    Target("YouTubeWeb", url="https://www.youtube.com", group="YouTube"),
    Target("YouTubeImage", url="https://i.ytimg.com", group="YouTube"),
    Target("YouTubeVideoRedirect", url="https://redirector.googlevideo.com", group="YouTube"),
    Target("GoogleMain", url="https://www.google.com", group="Google"),
    Target("CloudflareDNS1111", ping_host="1.1.1.1", group="DNS"),
)

# Цели быстрого прогона: хватает, чтобы отличить рабочую стратегию от нерабочей.
QUICK_NAMES = (
    "DiscordMain",
    "DiscordGateway",
    "DiscordCDN",
    "YouTubeWeb",
    "YouTubeImage",
    "YouTubeVideoRedirect",
)


def targets_file() -> Path:
    return paths.core_utils() / "targets.txt"


def parse(text: str) -> list[Target]:
    """Разбирает содержимое targets.txt.

    Заголовки вида `### Discord` используются как название группы — по ним
    результаты удобно складывать в таблицу.
    """
    found: list[Target] = []
    group = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("###"):
            group = line.lstrip("#").strip()
            continue
        if not line or line.startswith("#"):
            continue

        match = _LINE_RE.match(line)
        if not match:
            continue

        name, value = match.group(1), match.group(2).strip()
        if value.upper().startswith(_PING_PREFIX):
            found.append(Target(name, ping_host=value[len(_PING_PREFIX) :].strip(), group=group))
        else:
            found.append(Target(name, url=value, group=group))

    return found


def load(path: Path | None = None) -> list[Target]:
    """Загружает цели из сборки; при отсутствии файла берёт встроенный список."""
    path = path or targets_file()
    if not path.exists():
        return list(BUILTIN)

    try:
        parsed = parse(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return list(BUILTIN)

    return parsed or list(BUILTIN)


def quick(all_targets: list[Target] | None = None) -> list[Target]:
    """Подмножество для быстрого прогона."""
    source = all_targets if all_targets is not None else load()
    selected = [target for target in source if target.name in QUICK_NAMES]
    return selected or source[:6]
