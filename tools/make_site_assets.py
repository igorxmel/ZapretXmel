"""Картинки для сайта-визитки.

GitHub Pages раздаёт только то, что лежит внутри `docs/`, — на `assets/` и
`data/screenshots/` оттуда не сослаться. Поэтому картинки не копируются
руками, а готовятся здесь: исходники весят по полтора мегабайта каждый, и
класть их на страницу как есть нельзя.

    python tools/make_site_assets.py

Снимки экранов берутся из `data/screenshots/`. Если их там нет, сначала
выполните `python tools/screenshot.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Изображения масштабируются средствами Qt, который и так есть в проекте:
# тащить ради трёх картинок ещё одну библиотеку незачем.
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.diagnostics import vpn  # noqa: E402

ASSETS = ROOT / "assets"
SHOTS = ROOT / "data" / "screenshots"
TARGET = ROOT / "docs" / "assets"

# Ширина вдвое больше отображаемой: на экранах с удвоенной плотностью
# картинка иначе выходит мыльной.
BANNER_WIDTH = 1120
LOGO_WIDTH = 256
FAVICON_WIDTH = 64
SHOT_WIDTH = 1320

SCREENSHOTS = ("strategies", "diagnostics")

# Обзор и подбор показывают имя активного VPN — на странице, открытой всему
# интернету, это личные данные владельца. Поэтому они берутся только при
# выключенном туннеле.
VPN_SENSITIVE = ("dashboard", "autopick")


def resized(source: Path, width: int, target: Path) -> None:
    image = QImage(str(source))
    if image.isNull():
        raise SystemExit(f"не удалось прочитать {source}")

    scaled = image.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    if not scaled.save(str(target)):
        raise SystemExit(f"не удалось записать {target}")

    print(f"{target.relative_to(ROOT)}  ({target.stat().st_size // 1024} КБ)")


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)

    resized(ASSETS / "banner.png", BANNER_WIDTH, TARGET / "banner.png")
    resized(ASSETS / "logo.png", LOGO_WIDTH, TARGET / "logo.png")
    resized(ASSETS / "logo.png", FAVICON_WIDTH, TARGET / "favicon.png")

    wanted = list(SCREENSHOTS)
    tunnel = vpn.detect()
    if tunnel:
        print(
            f"\nснимки обзора и подбора пропущены: включён {tunnel.label}, "
            "и его название видно прямо на экране.\nВыключите VPN, пересоздайте "
            "снимки (python tools/screenshot.py) и запустите этот скрипт снова."
        )
    else:
        wanted += VPN_SENSITIVE

    missing = []
    for name in wanted:
        source = SHOTS / f"{name}.png"
        if not source.exists():
            missing.append(name)
            continue
        resized(source, SHOT_WIDTH, TARGET / f"{name}.png")

    if missing:
        print(
            "\nнет снимков: " + ", ".join(missing) + "\n"
            "сделайте их: python tools/screenshot.py"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
