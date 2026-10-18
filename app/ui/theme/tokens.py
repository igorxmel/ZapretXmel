"""Токены оформления.

Палитра намеренно монохромная: вся иерархия строится яркостью серого, а цвет
остаётся только за состояниями — работает, сломалось, требует внимания. Когда
цветных акцентов мало, они читаются с одного взгляда.

Всё оформление собирается отсюда, так что перекрасить приложение целиком можно
правкой одного этого файла.
"""

from __future__ import annotations

from typing import Final

# Тёмная палитра — та, с которой программа начиналась и которая остаётся
# по умолчанию: обход включают вечером, и светлое окно в темноте слепит.
DARK: Final[dict[str, str]] = {
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
    # Сердечко у тестировщиков — единственное место, где цвет не означает
    # состояния. Отдельным ключом, а не «danger»: тот красный говорит
    # «что-то сломалось», и менять его когда-нибудь придётся отдельно.
    "heart": "#ff5c6c",
    # Акцент основного действия — белый, без оттенка
    "accent": "#f2f2f3",
    "accent_hover": "#ffffff",
}

# Светлая — зеркало тёмной, а не другой интерфейс: те же роли у тех же
# ключей. Цвета состояний пришлось взять темнее: зелёный и жёлтый, годные
# на почти чёрном, на белом не читаются вовсе.
LIGHT: Final[dict[str, str]] = {
    # Фон заметно темнее карточек: на почти белом они не отделялись от
    # страницы вовсе, и экран читался как одно сплошное полотно.
    "bg": "#e8eaee",
    "surface": "#ffffff",
    "surface_hover": "#f0f1f5",
    "elevated": "#ffffff",
    "sidebar": "#dfe2e8",
    "border": "#d2d6de",
    "border_strong": "#a8adb8",
    "text": "#16161a",
    "text_dim": "#55555f",
    "text_muted": "#85858f",
    "text_inverted": "#ffffff",
    "success": "#157f4f",
    "danger": "#c02632",
    "warning": "#8a5d0a",
    "info": "#5a6672",
    # Темнее тёмной: светлый красный на белом не читается.
    "heart": "#d62839",
    # Зеркально тёмной: там основное действие белое на тёмном, здесь —
    # тёмное на белом.
    "accent": "#16161a",
    "accent_hover": "#000000",
}

# Текущая палитра. Словарь один и тот же на всё приложение: виджеты берут
# из него цвета по имени, а смена темы его переписывает.
COLORS: Final[dict[str, str]] = dict(DARK)

THEMES: Final[dict[str, dict[str, str]]] = {"dark": DARK, "light": LIGHT}

_current = "dark"


def apply_theme(name: str) -> str:
    """Переключает палитру. Возвращает применённое имя.

    Меняем содержимое того же словаря, а не ссылку: виджеты уже разобрали
    `COLORS` по импортам, и подмена ссылки до них бы не дошла.
    """
    global _current

    chosen = name if name in THEMES else "dark"
    COLORS.clear()
    COLORS.update(THEMES[chosen])
    _current = chosen
    return chosen


def system_theme() -> str:
    """Какая тема выбрана в самой Windows.

    Спрашиваем реестр напрямую: Qt о системном оформлении на Windows
    сообщает не везде одинаково, а ключ тут один и не менялся годами.
    Не прочитали — считаем тёмной: программу открывают вечером.
    """
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
    except (ImportError, OSError):
        return "dark"

    return "light" if light else "dark"


def current_theme() -> str:
    return _current


def is_light() -> bool:
    return _current == "light"


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
