"""Нарезает значки трея из одного листа.

Художник отдаёт их сеткой 4×3 в одном файле, а Qt нужен отдельный файл на
состояние. Резать руками в редакторе — значит делать это заново при каждой
правке листа и каждый раз по-своему обрезать поля.

    python tools/make_tray_icons.py

Столбцы — состояние обхода и прокси, строки — значок поверх него:

      обход    оба    Telegram   ничего
      ────────────────────────────────
      green    both   telegram   off        просто состояние
      …-update                              есть обновление
      …-alert                               сторож заметил поломку

Каждая клетка обрезается по своему содержимому и кладётся в квадрат: в
исходнике значки стоят неровно, и без обрезки они прыгали бы в трее на
пиксель-другой друг относительно друга.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
SHEET = ROOT / "tools" / "tray-sheet.png"
TARGET = ROOT / "assets" / "tray"

COLUMNS = ("bypass", "both", "telegram", "off")
ROWS = ("", "-update", "-alert")

# Значок в трее Windows показывается в 16 или 32 пикселя, но на экранах с
# увеличением просят и 48. Берём с запасом: уменьшать Qt умеет, увеличивать
# без мыла — нет.
SIZE = 128

# Поле вокруг значка, долей от размера. Впритык к краю он в трее выглядит
# крупнее соседних и обрезанным.
MARGIN = 0.03


def content_box(image: QImage, rect: QRect) -> QRect:
    """Находит в клетке прямоугольник, где есть хоть что-то непрозрачное."""
    left, top = rect.right(), rect.bottom()
    right, bottom = rect.left(), rect.top()

    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            if image.pixelColor(x, y).alpha() > 8:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)

    if right < left or bottom < top:
        raise SystemExit(f"пустая клетка в листе: {rect}")
    return QRect(left, top, right - left + 1, bottom - top + 1)


def square(image: QImage, box: QRect) -> QImage:
    """Кладёт вырезанное в квадрат, не растягивая и не обрезая."""
    side = max(box.width(), box.height())
    pad = int(side * MARGIN)
    side += pad * 2

    canvas = QImage(side, side, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.drawImage(
        (side - box.width()) // 2,
        (side - box.height()) // 2,
        image,
        box.x(),
        box.y(),
        box.width(),
        box.height(),
    )
    painter.end()

    return canvas.scaled(
        SIZE,
        SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def main() -> int:
    if not SHEET.exists():
        raise SystemExit(f"нет листа со значками: {SHEET.relative_to(ROOT)}")

    # Qt без поднятого приложения не умеет ни читать PNG, ни рисовать.
    app = QApplication(sys.argv[:1])

    sheet = QImage(str(SHEET)).convertToFormat(QImage.Format.Format_ARGB32)
    if sheet.isNull():
        raise SystemExit(f"не удалось прочитать {SHEET}")

    TARGET.mkdir(parents=True, exist_ok=True)

    cell_width = sheet.width() // len(COLUMNS)
    cell_height = sheet.height() // len(ROWS)

    for row, suffix in enumerate(ROWS):
        for column, state in enumerate(COLUMNS):
            cell = QRect(column * cell_width, row * cell_height, cell_width, cell_height)
            icon = square(sheet, content_box(sheet, cell))

            path = TARGET / f"{state}{suffix}.png"
            if not icon.save(str(path)):
                raise SystemExit(f"не удалось записать {path}")
            print(f"{path.relative_to(ROOT)}  ({path.stat().st_size // 1024} КБ)")

    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
