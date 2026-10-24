"""Готовит иконки приложения из исходного логотипа.

Логотип нарисован на залитом чёрном фоне без прозрачности, и сам рисунок тоже
богат чёрным: контуры цепи, тени, промежутки между звеньями. Поэтому прозрачность
нельзя получать ни порогом («тёмное — значит фон»), ни заливкой от краёв: и то и
другое съедает чёрные контуры рисунка вместе с фоном, потому что они с ним
связаны. Так и вышло в первой версии: на светлом фоне иконка теряла обводку.

Силуэт строится иначе: цветной рисунок плюс кайма в несколько пикселей. Чёрное
рядом с рисунком остаётся и работает контуром, а чёрный фон дальше каймы
становится прозрачным. Отверстие дужки и промежутки шире каймы прозрачны —
сквозь замок видно то, что за ним.

    python tools/make_icons.py
"""

from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QBuffer, QIODevice, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.ui.theme.tokens import DARK, LIGHT  # noqa: E402

ASSETS = Path(__file__).resolve().parents[1] / "assets"
SOURCE = ASSETS / "logo_original.png"
TRANSPARENT = ASSETS / "logo.png"
ICON = ASSETS / "logo.ico"

# Что считать рисунком. Чёрный фон после сжатия не идеально чёрный, а контур
# цепи — почти чёрный, но не совсем: порог отделяет именно такие оттенки.
ART_THRESHOLD = 40

# Ширина каймы вокруг рисунка в пикселях исходника (1254). Она и есть чёрная
# обводка силуэта: в трее на 32 пикселях это доля пикселя, а на рабочем столе
# в 256 — заметный контур.
OUTLINE_RADIUS = 14

# Число направлений, по которым рисунок «размазывается» в кайму. Больше —
# круглее край; 36 хватает, чтобы на глаз не было граней.
OUTLINE_STEPS = 36

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

CHEVRON_SIZE = 28
CHEVRON_THICKNESS = 2.6


def art_mask(image: QImage, threshold: int = ART_THRESHOLD) -> QImage:
    """Непрозрачные пиксели там, где нарисовано что-то не чёрное."""
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    count = width * height

    bits = image.constBits()
    bits.setsize(count * 4)
    raw = bytes(bits)
    blue, green, red = raw[0::4], raw[1::4], raw[2::4]

    alpha = bytes(
        255 if (b > threshold or g > threshold or r > threshold) else 0
        for b, g, r in zip(blue, green, red, strict=True)
    )

    buffer = bytearray(count * 4)
    buffer[0::4] = b"\xff" * count
    buffer[1::4] = b"\xff" * count
    buffer[2::4] = b"\xff" * count
    buffer[3::4] = alpha
    return QImage(bytes(buffer), width, height, QImage.Format.Format_ARGB32).copy()


def silhouette(image: QImage) -> QImage:
    """Рисунок, у которого прозрачен только фон далеко от самого рисунка.

    Силуэт — это рисунок, сдвинутый по кругу на радиус каймы: объединение
    сдвигов и есть расширение формы. Рисуется средствами Qt, а не по пикселям
    на Python: так быстрее на порядок.
    """
    width, height = image.width(), image.height()
    art = art_mask(image)

    grown = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    grown.fill(Qt.GlobalColor.transparent)
    painter = QPainter(grown)
    painter.drawImage(0, 0, art)
    for step in range(OUTLINE_STEPS):
        angle = 2 * math.pi * step / OUTLINE_STEPS
        painter.drawImage(
            round(OUTLINE_RADIUS * math.cos(angle)), round(OUTLINE_RADIUS * math.sin(angle)), art
        )
    painter.end()

    # Лёгкое сглаживание края: уменьшить и вернуть. Иначе кромка силуэта
    # получается лесенкой — ступеньки видны на крупной иконке.
    soft = grown.scaled(
        width // 4, height // 4, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).scaled(
        width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    result = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.drawImage(0, 0, image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, soft)
    painter.end()
    return result.convertToFormat(QImage.Format.Format_ARGB32)


def write_ico(frames: list[QImage], path: Path) -> None:
    """Пишет .ico со всеми размерами сразу, кадры внутри — PNG.

    Qt пишет в .ico один кадр, и Windows приходилось сжимать 256 пикселей до
    16 самой: на панели задач получалось мыло. Отдельный кадр под каждый размер
    система берёт как есть. PNG внутри .ico поддерживается начиная с Vista.
    """
    blobs = []
    for frame in frames:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        frame.save(buffer, "PNG")
        blobs.append(bytes(buffer.data()))

    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries = b""
    for frame, blob in zip(frames, blobs, strict=True):
        size = frame.width()
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,  # в заголовке 0 означает 256
            0 if size >= 256 else size,
            0, 0, 1, 32, len(blob), offset,
        )
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def draw_chevron(size: int, colour: str, thickness: float, up: bool = False) -> QImage:
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
    # Вверх — та же галочка, перевёрнутая: счётчикам нужны обе, и рисовать
    # их по отдельности значило бы получить две чуть разные стрелки.
    tip = -1 if up else 1
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(inset, middle - size * 0.1 * tip),
                QPointF(middle, middle + size * 0.16 * tip),
                QPointF(size - inset, middle - size * 0.1 * tip),
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
    cleaned = silhouette(source)
    cleaned.save(str(TRANSPARENT), "PNG")
    print(f"прозрачный фон: {TRANSPARENT}")

    frames = []
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
        frames.append(scaled)
    write_ico(frames, ICON)
    print(f"иконка: {ICON}, размеры {', '.join(str(s) for s in ICON_SIZES)}")

    # Стрелок четыре набора: вверх и вниз, для тёмной темы и для светлой.
    # Картинку Qt берёт из файла и перекрасить её не умеет, а стрелка цвета
    # тёмной темы на светлом фоне не видна вовсе.
    for theme, palette in (("", DARK), ("-light", LIGHT)):
        for state, colour in (("", palette["text_dim"]), ("-hover", palette["text"])):
            for direction, up in (("", False), ("-up", True)):
                name = f"chevron{direction}{theme}{state}"
                path = ASSETS / f"{name}.png"
                image = draw_chevron(CHEVRON_SIZE, colour, CHEVRON_THICKNESS, up=up)
                image.save(str(path), "PNG")
                print(f"стрелка: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
