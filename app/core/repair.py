"""Решения кнопки «Почини»: что пробовать и что считать успехом.

Сами проверки и перебор уже есть. Здесь только выбор, поэтому его можно проверить без сети
и без запуска winws.
"""

from __future__ import annotations

from app.core import coverage, stability
from app.core.probe.autopick import Report, StrategyScore

# Сколько стратегий пробуем первым, быстрым заходом. Полный перебор идёт минутами.
SHORTLIST_SIZE = 3

NOTHING: frozenset[str] = frozenset()


def shortlist(
    names: list[str], favorites: list[str], current: str, broken: list[str] | None = None
) -> list[str]:
    """Что пробовать сначала: избранное, затем лучшее по журналу.

    Если известно, что сломано, лучшее считается по этим сервисам: при сломанном YouTube нужна
    стратегия, у которой держится именно он.

    Текущую стратегию не берём: она только что не прошла проверку. Но если больше нечего
    пробовать, остаётся полный перебор.
    """
    available = [name for name in names if name != current]
    liked = [name for name in stability.rank(favorites, broken) if name in available]
    others = [name for name in stability.rank(available, broken) if name not in liked]
    return [*liked, *others][:SHORTLIST_SIZE]


def remaining(names: list[str], tried: list[str]) -> list[str]:
    return [name for name in names if name not in tried]


def check_passes(results: list, ignored: frozenset[str] = NOTHING) -> bool:
    """Всё, на что стратегия могла повлиять, работает."""
    return coverage.has_working_checks(results, ignored) and not coverage.broken_services(
        results, ignored
    )


def fully_works(score: StrategyScore | None, ignored: frozenset[str] = NOTHING) -> bool:
    return score is not None and check_passes(score.services, ignored)


def nothing_is_blocked(report: Report, ignored: frozenset[str] = NOTHING) -> bool:
    """Без обхода и так всё открывается: чинить нечего, и дело не в стратегии."""
    return fully_works(report.baseline, ignored)


def choose(report: Report) -> StrategyScore | None:
    """Стратегия, которую стоит включить. Нужно, чтобы она обошла замер без обхода."""
    return None if report.cancelled else report.best
