"""Картинки для сайта-визитки.

GitHub Pages раздаёт только то, что лежит внутри `docs/`, — на `assets/` и
`data/screenshots/` оттуда не сослаться. Поэтому картинки не копируются
руками, а готовятся здесь: исходники весят по полтора мегабайта каждый, и
класть их на страницу как есть нельзя.

    python tools/make_site_assets.py --shoot

С ключом `--shoot` снимки экранов делаются тут же; без него берутся те, что
уже лежат в `data/screenshots/`.

Обзор и подбор показывают название активного VPN прямо в окне, поэтому при
включённом туннеле снимать отказываемся: страница открыта всему интернету.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Изображения готовятся средствами Qt, который и так есть в проекте:
# тащить ради нескольких картинок ещё одну библиотеку незачем.
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QRadialGradient
from PyQt6.QtWidgets import QApplication

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

# Карточка для ссылок в мессенджерах. 1200×630 — размер, под который
# рисуют превью и Telegram, и Discord: баннер как есть они кладут на свою
# подложку, и прозрачный фон логотипа становится белым пятном.
CARD_SIZE = (1200, 630)
CARD_BANNER_WIDTH = 760

# Экраны для карусели. Остальные не годятся для публичной страницы: на
# Telegram видна ссылка с секретом прокси, в логах и настройках — пути с
# именем пользователя, в профилях — список его приложений.
SCREENSHOTS = ("strategies", "diagnostics", "updates")

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


def shoot() -> None:
    """Пересоздаёт снимки экранов перед подготовкой картинок."""
    print("снимаю экраны приложения…\n")
    result = subprocess.run(  # noqa: S603 — собственный скрипт проекта
        [sys.executable, str(ROOT / "tools" / "screenshot.py"), str(SHOTS)],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("не удалось снять экраны")
    print()


def social_card(target: Path) -> None:
    """Рисует картинку, которую покажут Telegram и Discord рядом со ссылкой."""
    from app.ui.theme.tokens import BRAND, COLORS

    width, height = CARD_SIZE
    card = QImage(width, height, QImage.Format.Format_ARGB32)
    card.fill(QColor(COLORS["bg"]))

    painter = QPainter(card)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    # То же зарево, что и на самой странице: иначе карточка выглядит
    # вырезанной из другого проекта.
    glow = QRadialGradient(QPointF(width / 2, -40), width * 0.75)
    glow.setColorAt(0.0, QColor(BRAND["orange"]).darker(150))
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.setOpacity(0.28)
    painter.fillRect(0, 0, width, height, glow)
    painter.setOpacity(1.0)

    banner = QImage(str(ASSETS / "banner.png"))
    if banner.isNull():
        raise SystemExit("не удалось прочитать assets/banner.png")

    banner = banner.scaledToWidth(CARD_BANNER_WIDTH, Qt.TransformationMode.SmoothTransformation)
    painter.drawImage(
        QPointF((width - banner.width()) / 2, height / 2 - banner.height() / 2 - 48),
        banner,
    )

    painter.setPen(QColor(COLORS["text_dim"]))
    painter.setFont(QFont("Segoe UI", 21))
    painter.drawText(
        QRectF(80, height - 210, width - 160, 70),
        int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
        "Свободный интернет каждому",
    )

    painter.setPen(QColor(COLORS["text_muted"]))
    painter.setFont(QFont("Consolas", 15))
    painter.drawText(
        QRectF(80, height - 150, width - 160, 60),
        int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
        "igorxmel.github.io/ZapretXmel",
    )

    # Оранжевая черта снизу — единственный акцент, как и на странице.
    painter.fillRect(QRectF(width / 2 - 60, height - 72, 120, 3), QColor(BRAND["orange"]))
    painter.end()

    if not card.save(str(target)):
        raise SystemExit(f"не удалось записать {target}")

    print(f"{target.relative_to(ROOT)}  ({target.stat().st_size // 1024} КБ)")


def main() -> int:
    # С --shoot снимки делаются тут же. Без него берутся те, что уже лежат
    # в data/screenshots.
    if "--shoot" in sys.argv:
        tunnel = vpn.detect()
        if tunnel:
            print(
                f"включён {tunnel.label}.\n\n"
                "Обзор и подбор показывают название туннеля прямо в окне, и на\n"
                "странице, открытой всему интернету, ему не место. Выключите VPN\n"
                "и запустите команду снова — снимки делаются секунд за двадцать,\n"
                "после этого VPN можно включить обратно."
            )
            return 1
        shoot()

    TARGET.mkdir(parents=True, exist_ok=True)

    resized(ASSETS / "banner.png", BANNER_WIDTH, TARGET / "banner.png")
    resized(ASSETS / "logo.png", LOGO_WIDTH, TARGET / "logo.png")
    resized(ASSETS / "logo.png", FAVICON_WIDTH, TARGET / "favicon.png")

    # Рисование текста требует поднятого приложения Qt — без него шрифты не
    # загружаются и подписи выходят пустыми прямоугольниками.
    app = QApplication(sys.argv[:1])
    social_card(TARGET / "og.png")
    app.quit()

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
