"""Пересоздаёт снимки для README — в обоих оформлениях.

Запускать **с выключенным VPN**: обзор и подбор показывают название активного
туннеля прямо в окне, а README открыт всем. Проверка стоит здесь и просто не даст
ошибиться.

    python tools/readme_shots.py

Оба оформления снимаются одним проходом: снятый отдельно светлый набор расходится с
тёмным — другая версия в углу, другое состояние службы. Однажды так на снимок попало
название включённого VPN.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402

from app.core.diagnostics import vpn  # noqa: E402

SHOTS = ROOT / "data" / "screenshots"
TARGET = ROOT / "media"
WIDTH = 1320
SCREENS = ("dashboard", "autopick", "diagnostics", "strategies", "updates")


def main() -> int:
    tunnel = vpn.detect()
    if tunnel:
        print(f"Включён {tunnel.label}: его название попало бы на снимки. Выключите VPN.")
        return 1

    for theme in ("dark", "light"):
        extra = [] if theme == "dark" else ["--light"]
        command = [sys.executable, str(ROOT / "tools" / "screenshot.py"), str(SHOTS), *extra]
        if subprocess.run(command, cwd=ROOT, check=False).returncode != 0:  # noqa: S603
            print(f"Не удалось снять экраны ({theme})")
            return 1

    TARGET.mkdir(exist_ok=True)
    for name in SCREENS:
        for suffix in ("", "-light"):
            image = QImage(str(SHOTS / f"{name}{suffix}.png"))
            if image.isNull():
                print(f"Нет снимка: {name}{suffix}")
                return 1
            scaled = image.scaledToWidth(WIDTH, Qt.TransformationMode.SmoothTransformation)
            scaled.save(str(TARGET / f"{name}{suffix}.png"))

    print(f"Готово: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
