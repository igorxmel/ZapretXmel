"""Шрифт интерфейса: как в Windows, один из встроенных или любой установленный.

Встроенные лежат в `assets/fonts` (лицензия OFL — их можно класть в программу) и
подключаются только к ней самой, в систему ничего не ставится. Свой шрифт
задаётся названием: человек вписывает то, что у него уже установлено.

Шрифт меняется на лету: таблица стилей собирается из `FONTS["ui"]`, и после
подмены её достаточно пересобрать.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PyQt6.QtGui import QFontDatabase

from app.core import paths
from app.ui.theme.tokens import FONTS

log = logging.getLogger(__name__)

SYSTEM = "Segoe UI"
# Запасные — на случай, если в выбранном нет какого-то знака: Qt берёт его отсюда.
_FALLBACK = "Segoe UI, Segoe UI Variable Text, sans-serif"
_DEFAULT_STACK = FONTS["ui"]

_bundled: list[str] = []


@dataclass(frozen=True)
class Support:
    """Что умеет шрифт: найден ли он и есть ли в нём русские и латинские буквы."""

    family: str
    found: bool
    cyrillic: bool = False
    latin: bool = False

    def describe(self) -> str:
        if not self.found:
            return (
                f"Шрифт «{self.family}» не найден. Проверьте название — оно должно "
                "совпадать с тем, что видно в «Параметры → Шрифты»."
            )
        if self.cyrillic and self.latin:
            return "Есть и русские, и латинские буквы."
        if self.latin:
            return "Только латиница: русский текст покажется запасным шрифтом."
        if self.cyrillic:
            return "Только кириллица: латинские буквы покажутся запасным шрифтом."
        return (
            "Это шрифт значков, а не букв: вместо латиницы в нём картинки, и интерфейс "
            "стал бы нечитаемым. Не применяю."
        )

    @property
    def usable(self) -> bool:
        """Можно ставить шрифтом интерфейса: есть хотя бы один из двух алфавитов."""
        return self.found and (self.cyrillic or self.latin)

    @property
    def complete(self) -> bool:
        return self.found and self.cyrillic and self.latin


def load_bundled() -> list[str]:
    """Подключает встроенные шрифты. Возвращает их семейства — для списка выбора."""
    if _bundled:
        return list(_bundled)
    folder = paths.assets_dir() / "fonts"
    for path in sorted(folder.glob("*.ttf")) if folder.is_dir() else []:
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            log.warning("Шрифт %s не подключился", path.name)
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family not in _bundled:
                _bundled.append(family)
    return list(_bundled)


def bundled() -> list[str]:
    return list(_bundled)


def find(name: str) -> str:
    """Точное имя семейства по названию без учёта регистра. Пусто — нет такого."""
    wanted = name.strip().casefold()
    if not wanted:
        return ""
    return next((f for f in QFontDatabase.families() if f.casefold() == wanted), "")


def support(name: str) -> Support:
    family = find(name)
    if not family:
        return Support(name.strip(), False)
    systems = QFontDatabase.writingSystems(family)
    return Support(
        family,
        True,
        cyrillic=QFontDatabase.WritingSystem.Cyrillic in systems,
        latin=QFontDatabase.WritingSystem.Latin in systems,
    )


def apply(name: str) -> str:
    """Делает шрифт шрифтом интерфейса. Пусто или не найден — как в Windows.

    Возвращает применённое семейство. Таблицу стилей пересобирает вызывающий.
    """
    found = support(name) if name else None
    family = found.family if found is not None and found.usable else ""
    if name and not family:
        # Настройки могли поправить руками, а шрифт — удалить из системы.
        log.warning("Шрифт «%s» не найден или без букв, остаётся системный", name)
    FONTS["ui"] = f'"{family}", {_FALLBACK}' if family else _DEFAULT_STACK
    return family or SYSTEM
