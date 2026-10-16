"""Токены оформления.

Палитра намеренно монохромная: вся иерархия строится яркостью серого, а цвет
остаётся только за состояниями — работает, сломалось, требует внимания. Когда
цветных акцентов мало, они читаются с одного взгляда.

Всё оформление собирается отсюда, так что перекрасить приложение целиком можно
правкой одного этого файла.
"""

from __future__ import annotations

from typing import Final

COLORS: Final[dict[str, str]] = {
    # Поверхности — от самой глубокой к самой приподнятой
    "bg": "#0b0b0c",
    "surface": "#141416",
    "surface_hover": "#1b1b1e",
    "elevated": "#202024",
    "sidebar": "#0e0e10",
    # Границы
    "border": "#282830",
    "border_strong": "#3a3a44",
    # Текст
    "text": "#f2f2f3",
    "text_dim": "#9f9fa6",
    "text_muted": "#68686f",
    "text_inverted": "#0b0b0c",
    # Состояния — единственный цвет во всём интерфейсе
    "success": "#4cc38a",
    "danger": "#f0616d",
    "warning": "#d9a441",
    "info": "#7d8590",
    # Акцент основного действия — белый, без оттенка
    "accent": "#f2f2f3",
    "accent_hover": "#ffffff",
}

SPACE: Final[dict[str, int]] = {
    "xs": 3,
    "sm": 6,
    "md": 10,
    "lg": 14,
    "xl": 20,
    "xxl": 28,
}

RADIUS: Final[dict[str, int]] = {
    "sm": 4,
    "md": 6,
    "lg": 8,
    "pill": 11,
}

SIZE: Final[dict[str, int]] = {
    "sidebar_width": 200,
    "window_min_width": 1060,
    "window_min_height": 700,
    "window_width": 1320,
    "window_height": 880,
    "row_height": 30,
    "control_height": 28,
}

# Segoe UI идёт первым намеренно: Segoe UI Variable появился только в Windows 11,
# и на десятке подстановка молча уводила бы шрифт в произвольный запасной.
FONTS: Final[dict[str, str]] = {
    "ui": "Segoe UI, Segoe UI Variable Text, Inter, sans-serif",
    "mono": "Cascadia Mono, Consolas, monospace",
    # Значки кнопок окна. Семейство обязано быть объявлено именно в стилях:
    # правило font-family для QWidget перебивает шрифт, выставленный кодом
    # через setFont, и значки подменяются случайными символами.
    "icons": '"Segoe Fluent Icons", "Segoe MDL2 Assets"',
}

FONT_SIZE: Final[dict[str, int]] = {
    "caption": 11,
    "body": 13,
    "subtitle": 14,
    "title": 18,
    "display": 26,
}

# Цвета логотипа. Оранжевый используется ровно в одном месте — выделение
# активного пункта в боковом меню, чтобы связать интерфейс со значком и не
# превратить его при этом в разноцветный.
BRAND: Final[dict[str, str]] = {
    "orange": "#f5a000",
    # Точка прокси в трее и подпись о нём: цвет самого Telegram.
    "telegram": "#2aabee",
    "green": "#8ebe3f",
}

# Цвет находки диагностики по её важности.
SEVERITY_COLORS: Final[dict[str, str]] = {
    "error": COLORS["danger"],
    "warning": COLORS["warning"],
    "info": COLORS["info"],
    "ok": COLORS["success"],
}

# Цвет исхода пробы в таблице результатов.
OUTCOME_COLORS: Final[dict[str, str]] = {
    "OK": COLORS["success"],
    "ERROR": COLORS["danger"],
    "SSL": COLORS["danger"],
    "UNSUP": COLORS["text_muted"],
}
