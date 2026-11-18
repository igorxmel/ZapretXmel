"""Смена оформления на ходу.

Масштаб интерфейса Qt читает один раз при запуске и поменять его потом
нельзя — отсюда и просьба перезапуститься. С темой иначе: таблицу стилей
можно пересобрать и повесить заново, и окно перекрасится сразу.

Это важнее, чем кажется: выбор темы предлагается при первом запуске, и
просить перезапуск сразу после установки — худшее, что можно сделать с
первым впечатлением.
"""

from __future__ import annotations

import logging

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from app.ui.theme.qss import build_stylesheet
from app.ui.theme.tokens import BRAND, apply_theme, system_theme

log = logging.getLogger(__name__)


def apply_palette(app: QApplication) -> None:
    """Цвет ссылок — фирменный оранжевый.

    Ссылку в обычной надписи (QLabel с разметкой) таблица стилей не красит: Qt берёт
    цвет из палитры, а там по умолчанию системный — в тёмной теме он выходил
    тёмно-розовым. Ссылки в размеченном тексте красит `widgets.set_markdown`.
    """
    palette = app.palette()
    orange = QColor(BRAND["orange"])
    for role in (QPalette.ColorRole.Link, QPalette.ColorRole.LinkVisited):
        palette.setColor(role, orange)
    app.setPalette(palette)


def use_theme(wanted: str) -> str:
    """Применяет тему немедленно. Возвращает применённое имя.

    «system» спрашивает Windows: пользователь выбирает не цвет, а правило,
    и правило должно выполняться при каждом запуске заново.
    """
    name = system_theme() if wanted == "system" else wanted
    applied = apply_theme(name)

    app = QApplication.instance()
    if app is not None:
        # Таблица стилей собирается из палитры, поэтому пересобрать её
        # нужно после смены, а не до.
        app.setStyleSheet(build_stylesheet())
        apply_palette(app)

    log.info("Оформление: %s", applied)
    return applied
