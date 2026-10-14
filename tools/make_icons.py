"""Готовит иконки приложения из исходного логотипа.

Логотип нарисован на залитом чёрном фоне без прозрачности. Просто объявить
все тёмные пиксели прозрачными нельзя — в рисунке полно чёрных контуров, и
они бы исчезли вместе с фоном. Поэтому прозрачность разливается волной от
краёв изображения и останавливается на светлых пикселях: контуры внутри
рисунка остаются нетронутыми, потому что до них заливка не дотягивается.

    python tools/make_icons.py
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.ui.theme.tokens import COLORS  # noqa: E402

ASSETS = Path(__file__).resolve().parents[1] / "assets"
SOURCE = ASSETS / "logo.png"
TRANSPARENT = ASSETS / "logo.png"
ICON = ASSETS / "logo.ico"

# Порог «считается фоном». Фон залит чистым чёрным, но после сжатия по краям
# остаются пиксели чуть светлее — с нулевым порогом заливка встала бы сразу.
BACKGROUND_THRESHOLD = 40

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

CHEVRON_SIZE = 28
CHEVRON_THICKNESS = 2.6


def strip_background(image: QImage, threshold: int = BACKGROUND_THRESHOLD) -> QImage:
    """Делает прозрачным фон, связанный с краями изображения."""
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()

    visited = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def consider(x: int, y: int) -> None:
        index = y * width + x
        if visited[index]:
            return
        visited[index] = 1
        colour = image.pixelColor(x, y)
        if max(colour.red(), colour.green(), colour.blue()) > threshold:
            return
        colour.setAlpha(0)
        image.setPixelColor(x, y, colour)
        queue.append((x, y))

    for x in range(width):
        consider(x, 0)
        consider(x, height - 1)
    for y in range(height):
        consider(0, y)
        consider(width - 1, y)

    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height:
                consider(nx, ny)

    return image


def draw_chevron(size: int, colour: str, thickness: float) -> QImage:
    """Рисует галочку-стрелку для выпадающих списков.

    Qt умеет ставить в `::down-arrow` только картинку — нарисовать её
    средствами таблицы стилей нельзя, а полагаться на символ из шрифта
    не стоит: у глифов свои поля, и стрелка съезжает с центра.
    """
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(colour), thickness, cap=Qt.PenCapStyle.RoundCap,
                        join=Qt.PenJoinStyle.RoundJoin))

    inset = size * 0.28
    middle = size / 2
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(inset, middle - size * 0.1),
                QPointF(middle, middle + size * 0.16),
                QPointF(size - inset, middle - size * 0.1),
            ]
        )
    )
    painter.end()
    return image


def main() -> int:
    app = QApplication(sys.argv[:1])  # noqa: F841 — нужен для работы с QImage

    source = QImage(str(SOURCE))
    if source.isNull():
        print(f"не удалось открыть {SOURCE}")
        return 1

    print(f"исходник: {source.width()}x{source.height()}")
    cleaned = strip_background(source)
    cleaned.save(str(TRANSPARENT), "PNG")
    print(f"прозрачный фон: {TRANSPARENT}")

    # Для .ico хватает самого крупного размера: Windows сама уменьшает его
    # под нужный контекст, а Qt пишет в файл один кадр.
    largest = cleaned.scaled(
        256,
        256,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    largest.save(str(ICON), "ICO")
    print(f"иконка: {ICON}")

    for size in ICON_SIZES:
        scaled = cleaned.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if scaled.isNull():
            print(f"  размер {size} не получился")
            return 1
    print(f"проверены размеры: {', '.join(str(s) for s in ICON_SIZES)}")

    for name, colour in (("chevron", COLORS["text_dim"]), ("chevron-hover", COLORS["text"])):
        path = ASSETS / f"{name}.png"
        draw_chevron(CHEVRON_SIZE, colour, CHEVRON_THICKNESS).save(str(path), "PNG")
        print(f"стрелка: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
