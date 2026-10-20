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

# Поля нет нарочно. Трей показывает значок в шестнадцати пикселях и сам
# отбивает соседей друг от друга; каждый процент поля — процент и без того
# крошечной картинки, потраченный на пустоту.
MARGIN = 0.0

# Пиксель считается закрашенным начиная с этой прозрачности. Края сглажены,
# и у самой кромки альфа падает почти до нуля — порог должен быть низким,
# иначе обводка обрезается вместе с фоном.
OPAQUE = 8


def bands(filled: list[bool]) -> list[tuple[int, int]]:
    """Разбивает строку признаков на полосы подряд идущих закрашенных."""
    found: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(filled):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            found.append((start, index - 1))
            start = None
    if start is not None:
        found.append((start, len(filled) - 1))
    return found


def grid(image: QImage) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Находит настоящие границы клеток — по пустым полосам между значками.

    Ровную сетку считать нельзя, и это выяснилось не сразу: значки на листе
    стоят с разными промежутками, и деление ширины на четыре отрезало
    у верхнего ряда пятнадцать пикселей снизу, а у нижнего восемь сверху.
    Со стороны значок выглядел целым — просто чуть обрубленным по краю.

    Заодно это переживёт новый лист: художник переставит значки или добавит
    строку, и резать по-прежнему будет по ним, а не по арифметике.
    """
    width, height = image.width(), image.height()

    # Шаг в два пикселя: полоса между значками заведомо шире, а проход по
    # полутора миллионам точек в лоб занимает минуты.
    rows = [
        any(image.pixelColor(x, y).alpha() > OPAQUE for x in range(0, width, 2))
        for y in range(height)
    ]
    columns = [
        any(image.pixelColor(x, y).alpha() > OPAQUE for y in range(0, height, 2))
        for x in range(width)
    ]

    return bands(rows), bands(columns)


def content_box(image: QImage, rect: QRect) -> QRect:
    """Обрезает клетку по тому, что в ней нарисовано.

    Полосы уже отделили значки друг от друга, но внутри своей полосы значок
    всё ещё стоит не по центру: без этой обрезки они прыгали бы в трее на
    пиксель-другой друг относительно друга.
    """
    left, top = rect.right(), rect.bottom()
    right, bottom = rect.left(), rect.top()

    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            if image.pixelColor(x, y).alpha() > OPAQUE:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)

    if right < left or bottom < top:
        raise SystemExit(f"пустая клетка в листе: {rect}")
    return QRect(left, top, right - left + 1, bottom - top + 1)


def square(image: QImage, box: QRect) -> QImage:
    """Кладёт вырезанное в квадрат, не растягивая и не обрезая.

    Растянуть до квадрата было бы заманчиво — значок занял бы всю клетку, —
    но значки разной ширины поплыли бы каждый по-своему, и один и тот же
    рисунок в соседних состояниях выглядел бы по-разному.
    """
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

    row_bands, column_bands = grid(sheet)
    if len(row_bands) != len(ROWS) or len(column_bands) != len(COLUMNS):
        raise SystemExit(
            f"на листе {len(row_bands)} строк и {len(column_bands)} столбцов, "
            f"а ожидается {len(ROWS)} и {len(COLUMNS)}"
        )

    for row, suffix in enumerate(ROWS):
        top, bottom = row_bands[row]
        for column, state in enumerate(COLUMNS):
            left, right = column_bands[column]
            cell = QRect(left, top, right - left + 1, bottom - top + 1)
            icon = square(sheet, content_box(sheet, cell))

            path = TARGET / f"{state}{suffix}.png"
            if not icon.save(str(path)):
                raise SystemExit(f"не удалось записать {path}")
            print(f"{path.relative_to(ROOT)}  ({path.stat().st_size // 1024} КБ)")

    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
