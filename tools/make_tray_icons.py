"""Готовит упрощённый логотип для значка в трее.

Исходник — `tools/tray-logo.webp`: тот же замок с хмелем, но без тонкой обводки и
мелких деталей, которые в шестнадцати пикселях сливаются в кашу. Из него
делается `assets/tray-logo.png`.

    python tools/make_tray_icons.py

Что делает скрипт и почему именно это:

- **Обрезает по рисунку.** Вокруг замка в исходнике пустое поле, и каждый его
  процент — это процент крошечного значка, потраченный впустую. Трей показывает
  шестнадцать пикселей, и значок должен занимать весь кадр.
- **Кладёт в квадрат, не растягивая.** Замок выше, чем шире; растянуть его до
  квадрата значило бы исказить рисунок.
- **Фон не вырезает.** Исходник уже с настоящей прозрачностью, в том числе в
  отверстии дужки. Заливка от краёв туда бы не добралась, а порог по белому
  съел бы блики на металле.

Кружки состояния и отметки сюда не входят: они рисуются в коде на каждый размер
значка отдельно (`app/ui/tray.py`), иначе пришлось бы хранить по картинке на
каждое сочетание состояний.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "tray-logo.webp"
TARGET = ROOT / "assets" / "tray-logo.png"

# Больше шестнадцати и тридцати двух трею не нужно, но при системном масштабе
# он просит и крупнее. Уменьшать Qt умеет, увеличивать без мыла — нет.
SIZE = 256

# Пиксель считается рисунком начиная с этой непрозрачности. Края сглажены, и у
# самой кромки альфа падает почти до нуля: порог низкий, иначе обводка обрезалась
# бы вместе с фоном.
OPAQUE = 8


def content_box(image: QImage) -> QRect:
    """Прямоугольник, в котором есть хоть что-то нарисованное."""
    left, top = image.width(), image.height()
    right = bottom = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > OPAQUE:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    if right < left or bottom < top:
        raise SystemExit("в исходнике нет ни одного непрозрачного пикселя")
    return QRect(left, top, right - left + 1, bottom - top + 1)


def square(image: QImage, box: QRect) -> QImage:
    side = max(box.width(), box.height())
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
    if not SOURCE.exists():
        raise SystemExit(f"нет исходника: {SOURCE.relative_to(ROOT)}")

    # Qt без поднятого приложения не умеет ни читать картинки, ни рисовать.
    app = QApplication(sys.argv[:1])

    source = QImage(str(SOURCE)).convertToFormat(QImage.Format.Format_ARGB32)
    if source.isNull():
        raise SystemExit(f"не удалось прочитать {SOURCE}")

    box = content_box(source)
    print(f"рисунок занимает {box.width()}x{box.height()} из {source.width()}x{source.height()}")

    icon = square(source, box)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if not icon.save(str(TARGET)):
        raise SystemExit(f"не удалось записать {TARGET}")
    print(f"{TARGET.relative_to(ROOT)}  ({TARGET.stat().st_size // 1024} КБ)")

    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
