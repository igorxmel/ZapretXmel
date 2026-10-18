"""Пересоздаёт все снимки для сайта — в обоих оформлениях.

Одна команда вместо трёх: снять экраны тёмными, снять светлыми, уменьшить
их под страницу и перерисовать картинку для ссылок в мессенджерах.

Запускать **с выключенным VPN**. Обзор и подбор показывают название
активного туннеля прямо в окне, а страница открыта всему интернету — на ней
ему не место. Проверка стоит здесь же и просто не даст ошибиться.

    python tools/site_shots.py

Занимает пару минут — оба набора снимаются подряд. После этого VPN можно
включать обратно.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.diagnostics import vpn  # noqa: E402


def main() -> int:
    tunnel = vpn.detect()
    if tunnel:
        print(
            f"Включён {tunnel.label}.\n\n"
            "Снимки обзора и подбора показывают название туннеля прямо в окне,\n"
            "а страница открыта всему интернету. Выключите VPN и запустите\n"
            "команду снова — это минута, потом можно включить обратно."
        )
        return 1

    print("Снимаю экраны и готовлю картинки для сайта…\n")
    result = subprocess.run(  # noqa: S603 — собственный скрипт проекта
        [sys.executable, str(ROOT / "tools" / "make_site_assets.py"), "--shoot"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode

    print(
        "\nГотово. Снимки лежат в data/screenshots (тёмные и «-light»),\n"
        "уменьшенные для страницы — в docs/assets."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
