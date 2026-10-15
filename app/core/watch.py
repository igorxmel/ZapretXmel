"""Сторож: замечает, что обход перестал работать.

Провайдеры меняют правила, и стратегия, работавшая неделю назад, однажды
перестаёт. Человек узнаёт об этом по сломавшемуся Discord, а не от программы,
и идёт подбирать заново, думая, что виновата программа.

Сторож раз в несколько минут выполняет ту же быструю проверку, что и кнопка на
главном экране, и говорит, если что-то отвалилось. По желанию — пробует
следующую избранную стратегию.

Решение вынесено в чистую функцию: подменять системные часы и сеть ради
проверки «а переключится ли он» никому не хочется.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Сколько стратегий сторож готов перебрать подряд, прежде чем замолчать.
# Дальше — дело подбора: он меряет честно, а сторож только latает.
MAX_SWITCHES = 3


@dataclass(frozen=True)
class Decision:
    """Что сторож решил сделать по итогам проверки."""

    broken: list[str]
    message: str = ""
    switch_to: str = ""

    @property
    def quiet(self) -> bool:
        """Правда, когда говорить не о чем."""
        return not self.message


def next_candidate(favorites: list[str], current: str, tried: list[str]) -> str:
    """Следующая избранная стратегия, которую ещё не пробовали.

    Берём только избранные: перебирать вслепую все двадцать две — это и есть
    подбор, и у него для этого есть честный замер и целый экран. Сторож же
    латает дыру тем, что человек сам отметил как рабочее.
    """
    for name in favorites:
        if name != current and name not in tried:
            return name
    return ""


def decide(
    broken: list[str],
    *,
    active: bool,
    vpn: bool,
    autoswitch: bool,
    favorites: list[str],
    current: str,
    tried: list[str],
) -> Decision:
    """Решает, что сказать и нужно ли менять стратегию."""
    if vpn:
        # Через туннель открывается всё подряд: проверка измеряет VPN, а не
        # провайдера, и её вывод ничего не значит.
        return Decision(broken=[])

    if not broken:
        return Decision(broken=[])

    listed = ", ".join(broken)
    if not active:
        # Обход выключен — значит ничего и не сломалось, так и задумано.
        return Decision(broken=broken)

    if not autoswitch:
        return Decision(broken=broken, message=f"Перестало работать: {listed}")

    if len(tried) >= MAX_SWITCHES:
        return Decision(
            broken=broken,
            message=(
                f"Перестало работать: {listed}. Перепробованы стратегии "
                f"({', '.join(tried)}) — дальше нужен подбор."
            ),
        )

    candidate = next_candidate(favorites, current, tried)
    if not candidate:
        return Decision(
            broken=broken,
            message=(
                f"Перестало работать: {listed}. Переключиться не на что — "
                "отметьте рабочие стратегии звёздочкой или запустите подбор."
            ),
        )

    return Decision(
        broken=broken,
        message=f"Перестало работать: {listed}. Пробую стратегию «{candidate}»",
        switch_to=candidate,
    )
