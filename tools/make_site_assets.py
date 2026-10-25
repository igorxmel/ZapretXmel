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
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QRadialGradient
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

# Картинка для настроек репозитория GitHub (Settings → General → Social preview).
# GitHub рекомендует 1280×640 и по краям подрезает и добавляет поля, поэтому всё
# важное держится в стороне от краёв. Это не карточка для мессенджеров: у той другая
# пропорция, и на GitHub она встала бы с полями.
PREVIEW_SIZE = (1280, 640)
PREVIEW_BANNER_WIDTH = 880

# GitHub показывает не всю картинку, а центральную полосу примерно 2,7:1 — сверху и
# снизу срезается около восьмой части. Всё, что должно быть видно, держится внутри
# неё: в первой версии строка со ссылкой внизу и верх логотипа оказались обрезаны.
PREVIEW_SAFE = (100, 540)

# Моноширинный, «терминальный»: на странице репозитория картинка соседствует с
# кодом, и такой шрифт читается как своя. Он должен стоять в системе — для
# картинки, которую рисуют раз в несколько месяцев, тащить шрифт в репозиторий
# незачем; запасные нужны, чтобы без него скрипт не упал, а нарисовал похоже.
PREVIEW_FONTS = ("Fira Code", "Cascadia Code", "Consolas")

# Поле слева и справа: GitHub подрезает картинку и по бокам на узких экранах.
PREVIEW_MARGIN = 70

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
    """Пересоздаёт снимки экранов перед подготовкой картинок.

    Оба оформления снимаются одним проходом здесь, а не двумя командами
    руками: светлый набор, снятый отдельно, расходится с тёмным — другая
    версия в углу, другое состояние службы, а однажды и включённый VPN,
    название которого видно прямо на экране. Проверка туннеля стоит перед
    этим вызовом и теперь прикрывает оба набора разом.
    """
    for theme in ("dark", "light"):
        print(f"снимаю экраны приложения ({theme})…\n")
        extra = [] if theme == "dark" else ["--light"]
        result = subprocess.run(  # noqa: S603 — собственный скрипт проекта
            [sys.executable, str(ROOT / "tools" / "screenshot.py"), str(SHOTS), *extra],
            cwd=ROOT,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(f"не удалось снять экраны ({theme})")
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


def trimmed(image: QImage, threshold: int = 8) -> QImage:
    """Обрезает прозрачные поля по краям.

    В файле баннера под рисунком запас прозрачных пикселей, и расстояние до текста
    ниже получалось не тем, что задано в коде: на глаз логотип и подпись висели
    по отдельности. После обрезки зазор считается от самого рисунка.
    """
    width, height = image.width(), image.height()
    rows = [
        y for y in range(height)
        if any(image.pixelColor(x, y).alpha() > threshold for x in range(0, width, 3))
    ]
    columns = [
        x for x in range(width)
        if any(image.pixelColor(x, y).alpha() > threshold for y in range(0, height, 3))
    ]
    if not rows or not columns:
        return image
    return image.copy(columns[0], rows[0], columns[-1] - columns[0] + 1, rows[-1] - rows[0] + 1)


def social_preview(target: Path) -> None:
    """Рисует картинку для репозитория: баннер, слоган и список возможностей."""
    from app.ui.theme.tokens import BRAND, COLORS

    width, height = PREVIEW_SIZE
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(COLORS["bg"]))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # Сетка, как у фона сайта: та же инженерная нота и опора для взгляда.
    painter.setPen(QPen(QColor(255, 255, 255, 9), 1))
    for x in range(0, width, 40):
        painter.drawLine(x, 0, x, height)
    for y in range(0, height, 40):
        painter.drawLine(0, y, width, y)

    glow = QRadialGradient(QPointF(width / 2, 40), width * 0.62)
    glow.setColorAt(0.0, QColor(BRAND["orange"]).darker(150))
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.setOpacity(0.30)
    painter.fillRect(0, 0, width, height, glow)
    painter.setOpacity(1.0)

    banner = QImage(str(ASSETS / "banner.png"))
    if banner.isNull():
        raise SystemExit("не удалось прочитать assets/banner.png")
    banner = trimmed(banner)

    # Группа — баннер и две строки под ним — собирается в одну колонку и ставится по
    # центру безопасной полосы. Расстояния между частями малы нарочно: чем ближе они,
    # тем больше читается как одно целое, а не как три отдельные вещи.
    from PyQt6.QtGui import QFontDatabase, QFontMetrics

    installed = set(QFontDatabase.families())
    family = next((name for name in PREVIEW_FONTS if name in installed), "Consolas")

    features = "обход блокировок  ·  подбор стратегии  ·  прокси для Telegram  ·  диагностика"

    # Кегль общий у обеих строк — слоган не должен быть ни крупнее, ни мельче второй
    # строки — и подбирается по ширине самой длинной: задать число и надеяться
    # нельзя, в первой версии строка вылезла за края и обрезала «о» в слове «обход».
    size = 28
    while size > 14:
        probe = QFont(family)
        probe.setPixelSize(size)
        if QFontMetrics(probe).horizontalAdvance(features) <= width - 2 * PREVIEW_MARGIN:
            break
        size -= 1

    gap_banner, gap_lines = 14, 4
    row = round(size * 1.6)
    low, high = PREVIEW_SAFE
    room = high - low - 10  # небольшой запас внутри безопасной полосы

    # Баннер как можно крупнее, но так, чтобы вся колонка влезла в безопасную полосу.
    text_height = gap_banner + row * 2 + gap_lines
    ratio = banner.width() / banner.height()
    banner_width = min(PREVIEW_BANNER_WIDTH, (room - text_height) * ratio)
    banner = banner.scaledToWidth(round(banner_width), Qt.TransformationMode.SmoothTransformation)

    stack = banner.height() + text_height
    top = low + (high - low - stack) / 2

    painter.drawImage(QPointF((width - banner.width()) / 2, top), banner)

    def line(text: str, y: float, colour: str, bold: bool) -> None:
        font = QFont(family)
        font.setPixelSize(size)
        font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(colour))
        painter.drawText(
            QRectF(PREVIEW_MARGIN, y, width - 2 * PREVIEW_MARGIN, row),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            text,
        )

    first = top + banner.height() + gap_banner
    line("Свободный интернет каждому", first, COLORS["text"], bold=True)
    line(features, first + row + gap_lines, COLORS["text_dim"], bold=False)
    print(
        f"баннер {banner.width()}x{banner.height()}; кегль {size}; шрифт: {family}; "
        f"колонка {round(top)}–{round(top + stack)} из безопасных {low}–{high}"
    )
    painter.end()

    if not image.save(str(target)):
        raise SystemExit(f"не удалось записать {target}")
    print(f"{target.relative_to(ROOT)}  ({target.stat().st_size // 1024} КБ)")


def main() -> int:
    # Только картинка для репозитория: без перерисовки всего остального и без
    # снимков экранов, а значит и без проверки на VPN.
    if "--preview" in sys.argv:
        app = QApplication(sys.argv[:1])
        TARGET.mkdir(parents=True, exist_ok=True)
        social_preview(TARGET / "social-preview.png")
        app.quit()
        return 0

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
        for suffix in ("", "-light"):
            source = SHOTS / f"{name}{suffix}.png"
            target = TARGET / f"{name}{suffix}.png"
            if not source.exists():
                # Светлый набор не обязателен: страница без него просто
                # покажет тёмные снимки, а это лучше, чем битая картинка.
                # Но прошлый светлый снимок тогда убираем: оставленный, он
                # показывал бы на странице другую версию программы — а один
                # раз показал и название включённого в тот момент VPN.
                if suffix:
                    target.unlink(missing_ok=True)
                else:
                    missing.append(name)
                continue
            resized(source, SHOT_WIDTH, target)

    if missing:
        print(
            "\nнет снимков: " + ", ".join(missing) + "\n"
            "сделайте их: python tools/screenshot.py"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
