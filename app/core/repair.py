"""Решения кнопки «Почини»: что пробовать и что считать успехом.

Сами проверки и перебор уже есть. Здесь только выбор, поэтому его можно проверить без сети
и без запуска winws.
"""

from __future__ import annotations

from app.core import stability
from app.core.probe.autopick import Report, StrategyScore

# Сколько стратегий пробуем первым, быстрым заходом. Полный перебор идёт минутами.
SHORTLIST_SIZE = 3


def shortlist(names: list[str], favorites: list[str], current: str) -> list[str]:
    """Что пробовать сначала: избранное, затем лучшее по журналу.

    Текущую стратегию не берём: она только что не прошла проверку. Но если больше нечего
    пробовать, остаётся полный перебор.
    """
    available = [name for name in names if name != current]
    liked = [name for name in stability.rank(favorites) if name in available]
    others = [name for name in stability.rank(available) if name not in liked]
    return [*liked, *others][:SHORTLIST_SIZE]


def remaining(names: list[str], tried: list[str]) -> list[str]:
    return [name for name in names if name not in tried]


def fully_works(score: StrategyScore | None) -> bool:
    return score is not None and bool(score.working_services) and not score.broken_services


def nothing_is_blocked(report: Report) -> bool:
    """Без обхода и так всё открывается: чинить нечего, и дело не в стратегии."""
    return fully_works(report.baseline)


def choose(report: Report) -> StrategyScore | None:
    """Стратегия, которую стоит включить. Нужно, чтобы она обошла замер без обхода."""
    return None if report.cancelled else report.best
