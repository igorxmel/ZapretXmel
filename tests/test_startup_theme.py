"""Тест запуска с оформлением «как в системе».

Эта ветка роняла программу шесть релизов подряд, и ни один тест её не
трогал: `app/ui/theme/__init__.py` не выставлял наружу `system_theme`,
а `__main__.apply_chosen_theme` звал его именно через пакет.

Падали при этом не все. Ветка берётся только когда в настройках стоит
«system» — а это значение по умолчанию, то есть у всех, кто ставил
программу заново. У тех, кто тему когда-то выбирал руками, в конфиге лежало
«dark» или «light», и до строки с падением дело не доходило. Со стороны
выглядело как «на одном компьютере обновилось, на другом перестало
запускаться вовсе».
"""

from __future__ import annotations

import pytest


def test_package_exports_everything_startup_uses() -> None:
    """Всё, что запуск берёт из пакета, пакет обязан отдавать.

    Проверка именно через пакет, а не через `tokens`: функция существовала
    всё это время, не хватало ровно строчки в `__init__`.
    """
    from app.ui import theme

    for name in ("apply_theme", "system_theme", "current_theme", "is_light"):
        assert hasattr(theme, name), f"app.ui.theme не отдаёт {name}"


def test_startup_applies_system_theme(monkeypatch: pytest.MonkeyPatch) -> None:
    """Запуск с темой по умолчанию доходит до конца и ставит живую тему."""
    from app import __main__ as entry
    from app.core.config import Settings
    from app.ui import theme

    monkeypatch.setattr(Settings, "load", staticmethod(lambda: Settings(theme="system")))

    entry.apply_chosen_theme()

    # «system» — это правило, а не цвет: применяться должна одна из палитр.
    assert theme.current_theme() in ("dark", "light")


def test_startup_survives_broken_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Битый конфиг не должен мешать программе открыться."""
    from app import __main__ as entry
    from app.core.config import Settings
    from app.ui import theme

    def explode() -> Settings:
        raise ValueError("конфиг испорчен")

    monkeypatch.setattr(Settings, "load", staticmethod(explode))

    entry.apply_chosen_theme()

    assert theme.current_theme() in ("dark", "light")
