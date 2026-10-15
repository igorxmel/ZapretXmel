"""Разбор стратегий Flowseal (`general*.bat`) в аргументы командной строки winws.

Воспроизводит логику установки службы из `service.bat` (метка `:service_install`):
берётся всё, что идёт после `winws.exe`, строки склеиваются по `^`, переменные
окружения раскрываются, а относительные пути в закавыченных аргументах
разворачиваются относительно корня сборки.

Модуль намеренно ничего не знает о конкретных флагах winws: любой новый флаг,
который появится в обновлении Flowseal, пройдёт через парсер без правок кода.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Кодировки, в которых Flowseal исторически сохранял .bat-файлы.
_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251", "cp866")

# Значение-заглушка, которое service.bat подставляет в GameFilter при
# выключенном игровом фильтре: порт 12 заведомо никем не используется.
GAME_FILTER_OFF = "12"

_SET_RE = re.compile(r'^\s*set\s+"?([A-Za-z_][A-Za-z0-9_]*)=([^"]*)"?\s*$', re.IGNORECASE)
_VAR_RE = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


@dataclass(frozen=True)
class Token:
    """Один аргумент командной строки и признак того, был ли он закавычен.

    Признак важен: `service.bat` разворачивает в абсолютный путь только те
    значения, которые в исходном .bat стояли в кавычках.
    """

    text: str
    quoted: bool


@dataclass(frozen=True)
class Section:
    """Одна секция командной строки winws (блоки разделяются флагом `--new`)."""

    args: list[str]

    @property
    def filters(self) -> list[str]:
        """Флаги отбора трафика — то, к чему секция применяется."""
        return [a for a in self.args if a.startswith(("--filter-", "--hostlist", "--ipset"))]

    @property
    def desync(self) -> str:
        """Режим обхода из `--dpi-desync=...`, если он задан."""
        for arg in self.args:
            if arg.startswith("--dpi-desync="):
                return arg.split("=", 1)[1]
        return ""

    def describe(self) -> str:
        """Короткое человекочитаемое описание секции для интерфейса."""
        proto = []
        for arg in self.args:
            if arg.startswith("--filter-tcp="):
                proto.append(f"TCP {arg.split('=', 1)[1]}")
            elif arg.startswith("--filter-udp="):
                proto.append(f"UDP {arg.split('=', 1)[1]}")
        lists = [Path(a.split("=", 1)[1]).name for a in self.args if a.startswith("--hostlist=")]
        parts = [", ".join(proto) or "весь трафик"]
        if self.desync:
            parts.append(f"обход: {self.desync}")
        if lists:
            parts.append("списки: " + ", ".join(lists))
        return " · ".join(parts)


@dataclass(frozen=True)
class StrategySpec:
    """Разобранная стратегия, готовая к запуску или установке в службу."""

    name: str
    path: Path
    argv: list[str]
    sections: list[Section] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.argv


class BatParseError(Exception):
    """В файле не нашлось пригодной для запуска командной строки winws."""


def read_bat(path: Path) -> str:
    """Читает .bat, перебирая кодировки, в которых их сохраняет апстрим."""
    raw = path.read_bytes()
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _join_continuations(text: str) -> list[str]:
    """Склеивает строки, перенесённые символом `^`, в логические строки."""
    logical: list[str] = []
    buffer = ""
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped.endswith("^") and stripped.count('"') % 2 == 0:
            buffer += stripped[:-1]
            continue
        buffer += stripped
        logical.append(buffer)
        buffer = ""
    if buffer:
        logical.append(buffer)
    return logical


def _collect_vars(lines: list[str], root: Path, extra: dict[str, str]) -> dict[str, str]:
    """Собирает значения переменных из `set`-строк файла.

    Имена приводятся к нижнему регистру: в cmd переменные регистронезависимы.
    """
    variables: dict[str, str] = {k.lower(): v for k, v in extra.items()}
    for line in lines:
        if "winws.exe" in line.lower():
            break
        match = _SET_RE.match(line)
        if not match:
            continue
        name, value = match.group(1).lower(), match.group(2)
        variables[name] = _expand(value, variables, root)
    return variables


def _expand(text: str, variables: dict[str, str], root: Path) -> str:
    """Раскрывает `%~dp0` и `%VAR%`; неизвестные переменные становятся пустыми."""
    text = text.replace("%~dp0", f"{root}\\")

    def replace(match: re.Match[str]) -> str:
        return variables.get(match.group(1).lower(), "")

    # Нескольких проходов достаточно: переменные в сборке вложены не глубже
    # пары уровней (%LISTS% -> %~dp0lists\).
    for _ in range(5):
        expanded = _VAR_RE.sub(replace, text)
        if expanded == text:
            break
        text = expanded
    return text


def _tokenize(line: str) -> list[Token]:
    """Разбивает строку на аргументы с учётом кавычек cmd."""
    tokens: list[Token] = []
    current = ""
    quoted = False
    in_quotes = False
    started = False

    for char in line:
        if char == '"':
            in_quotes = not in_quotes
            quoted = True
            started = True
            continue
        if char.isspace() and not in_quotes:
            if started:
                tokens.append(Token(current, quoted))
                current, quoted, started = "", False, False
            continue
        current += char
        started = True

    if started:
        tokens.append(Token(current, quoted))
    return tokens


def _absolutize(token: Token, root: Path) -> str:
    """Разворачивает относительный путь в абсолютный — как это делает service.bat.

    Трогаются только закавыченные значения: именно по этому признаку апстрим
    отличает пути от обычных значений вроде `--dpi-desync=fake,split`.
    """
    text = token.text
    if not token.quoted:
        return text

    flag, sep, value = text.partition("=")
    if not sep:
        flag, value = "", text

    if not value or ":" in value or value.startswith("\\\\"):
        return text

    prefix = ""
    if value.startswith("@"):
        prefix, value = "@", value[1:]

    resolved = f"{prefix}{root / value}"
    return f"{flag}={resolved}" if sep else resolved


def parse_bat(
    path: Path,
    *,
    root: Path | None = None,
    game_filter_tcp: str = GAME_FILTER_OFF,
    game_filter_udp: str = GAME_FILTER_OFF,
) -> StrategySpec:
    """Разбирает файл стратегии в готовый к запуску набор аргументов.

    `root` — корень сборки zapret; по умолчанию папка самого .bat.
    Диапазоны игрового фильтра подставляются вместо `%GameFilterTCP%` и
    `%GameFilterUDP%` так же, как это делает `service.bat`.
    """
    root = (root or path.parent).resolve()
    text = read_bat(path)
    lines = _join_continuations(text)

    extra = {
        "gamefilter": game_filter_tcp,
        "gamefiltertcp": game_filter_tcp,
        "gamefilterudp": game_filter_udp,
    }
    variables = _collect_vars(lines, root, extra)

    command_line = next((ln for ln in lines if "winws.exe" in ln.lower()), None)
    if command_line is None:
        raise BatParseError(f"{path.name}: не найден запуск winws.exe")

    tokens = _tokenize(_expand(command_line, variables, root))
    for index, token in enumerate(tokens):
        if token.text.lower().endswith("winws.exe"):
            tokens = tokens[index + 1 :]
            break
    else:
        raise BatParseError(f"{path.name}: не найден аргумент winws.exe")

    argv = [_absolutize(token, root) for token in tokens]
    argv = [arg for arg in argv if arg and arg != "^"]

    return StrategySpec(
        name=path.stem,
        path=path,
        argv=argv,
        sections=split_sections(argv),
    )


def split_sections(argv: list[str]) -> list[Section]:
    """Делит аргументы на секции по разделителю `--new`."""
    sections: list[Section] = []
    current: list[str] = []
    for arg in argv:
        if arg == "--new":
            sections.append(Section(current))
            current = []
            continue
        current.append(arg)
    if current:
        sections.append(Section(current))
    return sections


def to_service_binpath(exe: Path, argv: list[str]) -> str:
    """Собирает значение `binPath=` для `sc create`.

    Повторяет формат, который строит `service.bat`: путь к exe в кавычках,
    затем аргументы; значения с пробелами закавычиваются.
    """
    parts = [f'"{exe}"']
    for arg in argv:
        flag, sep, value = arg.partition("=")
        if sep and " " in value:
            parts.append(f'{flag}="{value}"')
        elif " " in arg:
            parts.append(f'"{arg}"')
        else:
            parts.append(arg)
    return " ".join(parts)
