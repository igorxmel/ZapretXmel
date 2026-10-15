"""Сборка одной стратегии из частей нескольких.

Бывает, что одна стратегия чинит Discord, другая — YouTube, а обе сразу не
умеет никто. Стратегия при этом устроена как цепочка секций, разделённых
`--new`: у каждой свой фильтр (порты, списки доменов, ipset) и свой способ
обхода. Значит рабочие секции разных стратегий в принципе можно соединить.

Три вещи, из-за которых это нельзя сделать простым склеиванием:

* Флаги уровня ядра (`--wf-tcp`, `--wf-udp`) общие на всю команду и стоят
  в начале. Их приходится объединять как объединение портов, иначе часть
  трафика просто не попадёт в перехват.
* Применяется **первая подходящая** секция, поэтому широкая секция затеняет
  узкую. Отсюда порядок: сначала идут секции стратегии, выигравшей более
  «узкий» сервис, и только потом остальные.
* Соответствие «секция — сервис» нигде не записано, и восстановить его можно
  лишь приблизительно.

Из-за последнего пункта результат здесь считается не готовым решением, а
кандидатом: собранную стратегию обязательно перемеряют тем же прогоном, что и
обычные, и принимают только если она действительно оказалась лучше исходных.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.core import paths
from app.core.batfile import Section, StrategySpec, split_sections

log = logging.getLogger(__name__)

KERNEL_PREFIX = "--wf-"
MERGED_SUFFIX = "сборка"

# Перенос строки для .bat задаётся явно при записи. Если положить готовый CRLF
# прямо в текст, Python добавит к нему свой и выйдет двойной возврат каретки.
# От появившихся пустых строк разваливается склейка продолжений по «^»:
# командная строка обрывается сразу после winws.exe, и стратегия запускается
# вообще без аргументов.
WINDOWS_NEWLINE = "\r\n"


@dataclass(frozen=True)
class MergePlan:
    """Из чего собирается стратегия."""

    sources: dict[str, str] = field(default_factory=dict)

    @property
    def strategy_names(self) -> list[str]:
        """Исходные стратегии в порядке первого появления, без повторов."""
        seen: list[str] = []
        for name in self.sources.values():
            if name not in seen:
                seen.append(name)
        return seen

    @property
    def is_useful(self) -> bool:
        """Собирать есть смысл, только если сервисы выиграли разные стратегии."""
        return len(self.strategy_names) > 1

    def describe(self) -> str:
        return "; ".join(f"{service} — «{name}»" for service, name in self.sources.items())


def plan_from_winners(winners: dict[str, str]) -> MergePlan:
    """Строит план по словарю «сервис → лучшая для него стратегия».

    Порядок словаря сохраняется: его задаёт отчёт, и сервисы приходят от
    самого мелкого к крупному, чтобы узкие секции встали раньше широких.
    """
    return MergePlan(sources=dict(winners))


def kernel_flags(spec: StrategySpec) -> list[str]:
    return [arg for arg in spec.argv if arg.startswith(KERNEL_PREFIX)]


def rule_sections(spec: StrategySpec) -> list[Section]:
    """Секции стратегии без флагов уровня ядра."""
    cleaned: list[Section] = []
    for section in spec.sections:
        args = [arg for arg in section.args if not arg.startswith(KERNEL_PREFIX)]
        if args:
            cleaned.append(Section(args))
    return cleaned


def merge_kernel_flags(specs: list[StrategySpec]) -> list[str]:
    """Объединяет `--wf-*` всех стратегий, складывая списки портов.

    Повторы убираются, порядок первого появления сохраняется: winws принимает
    порты в произвольном порядке, а так результат легче читать и сравнивать.
    """
    merged: dict[str, list[str]] = {}

    for spec in specs:
        for flag in kernel_flags(spec):
            name, _, value = flag.partition("=")
            ports = merged.setdefault(name, [])
            for raw in value.split(","):
                token = raw.strip()
                if token and token not in ports:
                    ports.append(token)

    return [f"{name}={','.join(ports)}" for name, ports in merged.items() if ports]


def merge(specs: list[StrategySpec]) -> list[str]:
    """Собирает аргументы winws из нескольких стратегий.

    Одинаковые секции отбрасываются: у родственных стратегий часть секций
    совпадает дословно, и дубликаты только удлиняли бы командную строку.
    """
    if not specs:
        return []
    if len(specs) == 1:
        return list(specs[0].argv)

    seen: set[tuple[str, ...]] = set()
    sections: list[Section] = []

    for spec in specs:
        for section in rule_sections(spec):
            key = tuple(section.args)
            if key in seen:
                continue
            seen.add(key)
            sections.append(section)

    # Флаги ядра встают в начало первой секции, а не отдельным блоком перед
    # «--new». Отдельный блок стал бы профилем без единого фильтра, то есть
    # подходящим под любой пакет, — и, по правилу «применяется первая
    # подходящая секция», затенил бы собой все остальные.
    argv: list[str] = merge_kernel_flags(specs)
    for index, section in enumerate(sections):
        if index:
            argv.append("--new")
        argv.extend(section.args)

    return argv


def merged_name() -> str:
    return f"general ({MERGED_SUFFIX})"


def is_merged(name: str) -> bool:
    return f"({MERGED_SUFFIX})" in name


def to_bat(argv: list[str], plan: MergePlan, root: Path | None = None) -> str:
    """Готовит содержимое .bat — такое же, как у штатных стратегий.

    Собранная стратегия сохраняется обычным файлом сборки, а не особой
    сущностью: тогда её видят и наш список стратегий, и консольное меню
    апстрима, и она переживает обновление ядра наравне с пользовательскими.
    """
    root = root or paths.core_dir()

    lines = [
        "@echo off",
        "chcp 65001 > nul",
        ":: Стратегия собрана программой ZapretXmel из частей:",
        f":: {plan.describe()}",
        ":: Её можно править руками — формат обычный.",
        "",
        'cd /d "%~dp0"',
        "",
        f'set "BIN={root / "bin"}\\"',
        "",
        'start "zapret: %~n0" /min "%BIN%winws.exe" ^',
    ]

    # Каждая секция — своей строкой, как в оригинальных файлах сборки:
    # так командную строку можно читать и править глазами.
    chunks: list[list[str]] = [[]]
    for arg in argv:
        chunks[-1].append(arg)
        if arg == "--new":
            chunks.append([])

    body = [" ".join(chunk) for chunk in chunks if chunk]
    for index, line in enumerate(body):
        lines.append(line + (" ^" if index < len(body) - 1 else ""))

    return "\n".join(lines) + "\n"


def save(argv: list[str], plan: MergePlan, root: Path | None = None) -> Path:
    """Сохраняет собранную стратегию в папку ядра."""
    root = root or paths.core_dir()
    path = root / f"{merged_name()}.bat"
    path.write_text(to_bat(argv, plan, root), encoding="utf-8", newline=WINDOWS_NEWLINE)
    log.info("Собранная стратегия сохранена: %s", path.name)
    return path


def build(specs: list[StrategySpec], plan: MergePlan) -> tuple[list[str], list[Section]]:
    """Возвращает аргументы сборки и её секции — для показа перед сохранением."""
    argv = merge(specs)
    return argv, split_sections(argv)
