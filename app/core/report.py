"""Текст отчёта о поломке для задачи на GitHub.

Собирается из того же снимка, что и пакет для нейросети: имя пользователя и публичные адреса
из него уже вычищены. Человек видит текст до отправки, а программа сама ничего не отправляет.
"""

from __future__ import annotations

import json

from app import __version__
from app.core.diagnostics import snapshot

LOG_LINES = 40


def build_text(data: dict | None = None) -> str:
    """Готовый текст в разметке GitHub. `data` — снимок, его можно подставить в тестах."""
    state = data if data is not None else snapshot.build(sanitized=True, log_lines=LOG_LINES)

    lines = [f"**Версия программы:** {__version__}", ""]

    findings = state.get("находки") or []
    lines.append("**Что нашла диагностика:**")
    for item in findings:
        lines.append(f"- {item.get('важность', '')}: {item.get('что', '')}.")
        if item.get("подробности"):
            lines[-1] += f" {item['подробности']}"
    if not findings:
        lines.append("- ничего")
    lines.append("")

    sections = ("обстановка", "ядро", "обход", "настройки сборки", "система")
    overview = {key: state.get(key) for key in sections}
    lines += [
        "<details><summary>Состояние</summary>",
        "",
        "```json",
        json.dumps(overview, ensure_ascii=False, indent=1, default=str),
        "```",
        "",
        "</details>",
        "",
        "<details><summary>Журнал</summary>",
        "",
        "```text",
        *[str(line) for line in state.get("лог") or []],
        "```",
        "",
        "</details>",
    ]
    return "\n".join(lines)
