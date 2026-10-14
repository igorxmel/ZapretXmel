"""Снимок состояния сети для разбора задним числом.

Нужен, когда проверять и чинить приходится в разное время: достаточно один раз
прогнать скрипт при выключенном VPN, а отчёт прочитать позже. Ничего не меняет
в системе и не требует прав администратора — только измеряет.

    python tools/selfcheck.py

Отчёт сохраняется в `data/reports/` и дублируется на экран.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import coreinfo, paths, service, winws  # noqa: E402
from app.core.diagnostics import vpn  # noqa: E402
from app.core.probe import discord, dpi, targets  # noqa: E402
from app.core.probe.http import check_target, supported_protocols  # noqa: E402

DPI_SAMPLE = 6
SEPARATOR = "-" * 72


class Report:
    """Копит строки отчёта и одновременно печатает их."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, text: str = "") -> None:
        self.lines.append(text)
        print(text, flush=True)

    def section(self, title: str) -> None:
        self.add()
        self.add(SEPARATOR)
        self.add(title.upper())
        self.add(SEPARATOR)

    def save(self) -> Path:
        directory = paths.data_dir() / "reports"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"selfcheck-{datetime.now():%Y%m%d-%H%M%S}.txt"
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        return path


def describe_environment(report: Report) -> bool:
    """Печатает обстановку и возвращает True, если замер можно считать честным."""
    report.section("обстановка")

    tunnel = vpn.detect()
    report.add(f"VPN:            {tunnel.label if tunnel else 'выключен'}")

    core = coreinfo.describe()
    report.add(f"Ядро:           {core.version_label}, стратегий {core.strategy_count}")
    report.add(f"Служба zapret:  {service.LABELS[service.query_state()]}")
    report.add(f"Стратегия:      {service.installed_strategy() or '—'}")
    report.add(f"Процессов winws: {winws.count_instances()}")
    report.add(f"Протоколы:      {', '.join(name for name, _ in supported_protocols())}")

    if tunnel is not None:
        report.add()
        report.add("!!! ВНИМАНИЕ: включён VPN. Замер покажет туннель, а не провайдера.")
        report.add("!!! Выключите VPN и запустите скрипт заново.")
        return False
    return True


def check_discord(report: Report) -> None:
    report.section("discord по шагам")
    results = discord.check_all()
    for result in results:
        mark = "OK  " if result.ok else "СБОЙ"
        report.add(f"{mark}  {result.title}")
        report.add(f"        ответ: {result.detail}, {result.elapsed_ms:.0f} мс")
    report.add()
    report.add(discord.summarise(results))


def check_sites(report: Report) -> None:
    report.section("сайты (заголовки страниц)")
    for target in targets.quick(targets.load()):
        result = check_target(target, timeout=6)
        tokens = "  ".join(f"{p.protocol}:{p.outcome}" for p in result.probes)
        ping = f"{result.ping_ms:.0f} мс" if result.ping_ms is not None else "нет ответа"
        report.add(f"{target.name:24} {tokens:34} пинг: {ping}")


def check_dpi(report: Report) -> None:
    report.section(f"передача данных (первые {DPI_SAMPLE} хостов)")
    try:
        suite = dpi.load_suite()
    except Exception as error:  # noqa: BLE001 — отчёт важнее одной упавшей проверки
        report.add(f"Не удалось скачать набор хостов: {error}")
        return

    payload = dpi.make_payload()
    try:
        for target in suite[:DPI_SAMPLE]:
            result = dpi.check_target(target, payload, timeout=8)
            cells = "  ".join(
                f"{line.protocol}:{line.status}({line.down_bytes}б)" for line in result.lines
            )
            report.add(f"{target.id:16} {cells}")
    finally:
        payload.unlink(missing_ok=True)


def main() -> int:
    paths.ensure_dirs()
    report = Report()

    report.add("ОТЧЁТ О СОСТОЯНИИ СЕТИ")
    report.add(f"время: {datetime.now():%Y-%m-%d %H:%M:%S}")

    honest = describe_environment(report)
    check_discord(report)
    check_sites(report)
    check_dpi(report)

    report.section("итог")
    if not honest:
        report.add("Замер сделан через VPN — доверять ему нельзя.")
    else:
        report.add("Замер сделан напрямую, без туннеля.")

    path = report.save()
    report.add()
    report.add(f"Отчёт сохранён: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
