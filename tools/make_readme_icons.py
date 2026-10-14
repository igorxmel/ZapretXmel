"""Рисует значки для заголовков разделов README.

Чужие CDN с иконками сюда не годятся по двум причинам: монохромные наборы
отдают чёрные глифы, которые пропадают на тёмной теме GitHub, а у цветных
бывают условия вроде обязательной ссылки на источник. Свои значки снимают оба
вопроса и заодно держат README в цветах логотипа.

    python tools/make_readme_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.ui.theme.tokens import BRAND, COLORS  # noqa: E402

ICONS = Path(__file__).resolve().parents[1] / "assets" / "icons"

# Рисуем крупно и уменьшаем при показе: на экранах с высокой плотностью
# значок остаётся чётким.
SIZE = 96
STROKE = 7.0

ORANGE = BRAND["orange"]
GREEN = BRAND["green"]
GREY = COLORS["text_dim"]


def _canvas() -> tuple[QImage, QPainter]:
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return image, painter


def _pen(colour: str, width: float = STROKE) -> QPen:
    return QPen(
        QColor(colour),
        width,
        cap=Qt.PenCapStyle.RoundCap,
        join=Qt.PenJoinStyle.RoundJoin,
    )


def sparkle(painter: QPainter) -> None:
    """Четырёхлучевая звезда — «возможности»."""
    centre, outer, inner = SIZE / 2, SIZE * 0.44, SIZE * 0.14

    # Вершины по кругу: луч, впадина, луч, впадина — и так четыре раза.
    points = [
        (centre, centre - outer),
        (centre + inner, centre - inner),
        (centre + outer, centre),
        (centre + inner, centre + inner),
        (centre, centre + outer),
        (centre - inner, centre + inner),
        (centre - outer, centre),
        (centre - inner, centre - inner),
    ]

    path = QPainterPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    path.closeSubpath()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ORANGE))
    painter.drawPath(path)


def download(painter: QPainter) -> None:
    """Стрелка вниз над подставкой — «установка»."""
    painter.setPen(_pen(ORANGE))
    painter.drawLine(QPointF(SIZE / 2, SIZE * 0.18), QPointF(SIZE / 2, SIZE * 0.58))
    painter.drawLine(QPointF(SIZE * 0.3, SIZE * 0.42), QPointF(SIZE / 2, SIZE * 0.62))
    painter.drawLine(QPointF(SIZE * 0.7, SIZE * 0.42), QPointF(SIZE / 2, SIZE * 0.62))
    painter.setPen(_pen(GREY))
    painter.drawLine(QPointF(SIZE * 0.22, SIZE * 0.8), QPointF(SIZE * 0.78, SIZE * 0.8))


def monitor(painter: QPainter) -> None:
    """Экран на ножке — «требования»."""
    painter.setPen(_pen(GREY))
    painter.drawRoundedRect(QRectF(SIZE * 0.14, SIZE * 0.2, SIZE * 0.72, SIZE * 0.48), 8, 8)
    painter.setPen(_pen(ORANGE))
    painter.drawLine(QPointF(SIZE / 2, SIZE * 0.68), QPointF(SIZE / 2, SIZE * 0.8))
    painter.drawLine(QPointF(SIZE * 0.32, SIZE * 0.82), QPointF(SIZE * 0.68, SIZE * 0.82))


def box(painter: QPainter) -> None:
    """Коробка — «что внутри»."""
    painter.setPen(_pen(GREY))
    painter.drawRoundedRect(QRectF(SIZE * 0.16, SIZE * 0.3, SIZE * 0.68, SIZE * 0.52), 8, 8)
    painter.setPen(_pen(ORANGE))
    painter.drawLine(QPointF(SIZE * 0.16, SIZE * 0.47), QPointF(SIZE * 0.84, SIZE * 0.47))
    painter.drawLine(QPointF(SIZE / 2, SIZE * 0.47), QPointF(SIZE / 2, SIZE * 0.82))


def target(painter: QPainter) -> None:
    """Мишень — «чем отличается подбор»."""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(_pen(GREY))
    painter.drawEllipse(QRectF(SIZE * 0.14, SIZE * 0.14, SIZE * 0.72, SIZE * 0.72))
    painter.setPen(_pen(ORANGE))
    painter.drawEllipse(QRectF(SIZE * 0.33, SIZE * 0.33, SIZE * 0.34, SIZE * 0.34))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(GREEN))
    painter.drawEllipse(QRectF(SIZE * 0.44, SIZE * 0.44, SIZE * 0.12, SIZE * 0.12))


def code(painter: QPainter) -> None:
    """Угловые скобки — «разработка»."""
    painter.setPen(_pen(GREY))
    painter.drawLine(QPointF(SIZE * 0.36, SIZE * 0.26), QPointF(SIZE * 0.18, SIZE / 2))
    painter.drawLine(QPointF(SIZE * 0.18, SIZE / 2), QPointF(SIZE * 0.36, SIZE * 0.74))
    painter.drawLine(QPointF(SIZE * 0.64, SIZE * 0.26), QPointF(SIZE * 0.82, SIZE / 2))
    painter.drawLine(QPointF(SIZE * 0.82, SIZE / 2), QPointF(SIZE * 0.64, SIZE * 0.74))
    painter.setPen(_pen(ORANGE, STROKE * 0.8))
    painter.drawLine(QPointF(SIZE * 0.56, SIZE * 0.2), QPointF(SIZE * 0.44, SIZE * 0.8))


def branch(painter: QPainter) -> None:
    """Ветка — «как помочь»."""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(_pen(GREY))
    painter.drawLine(QPointF(SIZE * 0.3, SIZE * 0.26), QPointF(SIZE * 0.3, SIZE * 0.74))
    path = QPainterPath()
    path.moveTo(SIZE * 0.3, SIZE * 0.52)
    path.cubicTo(SIZE * 0.3, SIZE * 0.3, SIZE * 0.7, SIZE * 0.52, SIZE * 0.7, SIZE * 0.34)
    painter.setPen(_pen(ORANGE))
    painter.drawPath(path)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(GREY))
    for point in (QPointF(SIZE * 0.3, SIZE * 0.22), QPointF(SIZE * 0.3, SIZE * 0.78)):
        painter.drawEllipse(point, SIZE * 0.08, SIZE * 0.08)
    painter.setBrush(QColor(GREEN))
    painter.drawEllipse(QPointF(SIZE * 0.7, SIZE * 0.3), SIZE * 0.08, SIZE * 0.08)


def heart(painter: QPainter) -> None:
    """Сердце — «благодарности» и «поддержка»."""
    path = QPainterPath()
    bottom = QPointF(SIZE / 2, SIZE * 0.82)
    path.moveTo(bottom)
    path.cubicTo(
        QPointF(SIZE * 0.02, SIZE * 0.52),
        QPointF(SIZE * 0.2, SIZE * 0.12),
        QPointF(SIZE / 2, SIZE * 0.36),
    )
    path.cubicTo(
        QPointF(SIZE * 0.8, SIZE * 0.12),
        QPointF(SIZE * 0.98, SIZE * 0.52),
        bottom,
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ORANGE))
    painter.drawPath(path)


def hop(painter: QPainter) -> None:
    """Шишка хмеля — «поддержка». Отсылка к логотипу."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(GREEN))
    rows = ((0.5,), (0.38, 0.62), (0.3, 0.5, 0.7), (0.38, 0.62), (0.5,))
    for index, row in enumerate(rows):
        y = SIZE * (0.22 + index * 0.14)
        for x in row:
            painter.drawEllipse(QPointF(SIZE * x, y), SIZE * 0.1, SIZE * 0.085)


DRAWINGS = {
    "sparkle": sparkle,
    "download": download,
    "monitor": monitor,
    "box": box,
    "target": target,
    "code": code,
    "branch": branch,
    "heart": heart,
    "hop": hop,
}


def main() -> int:
    app = QApplication(sys.argv[:1])  # noqa: F841 — нужен для работы с QImage
    ICONS.mkdir(parents=True, exist_ok=True)

    for name, draw in DRAWINGS.items():
        image, painter = _canvas()
        draw(painter)
        painter.end()

        path = ICONS / f"{name}.png"
        image.save(str(path), "PNG")
        print(f"  {path.name}")

    print(f"\nготово: {len(DRAWINGS)} значков в {ICONS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
