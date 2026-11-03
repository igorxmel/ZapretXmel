"""Адреса для добровольной поддержки проекта.

Адрес кошелька не секрет, его можно публиковать. Секретна только фраза восстановления,
и в этот файл она попасть не должна ни при каких обстоятельствах.

Адрес меняется только вместе с новой версией программы, а не загружается из сети: подмена
файла на сервере незаметно отправляла бы деньги чужому человеку.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Wallet:
    """Один адрес. Сеть обязательна: перевод в другой сети может пропасть."""

    coin: str
    network: str
    address: str

    @property
    def title(self) -> str:
        return f"{self.coin} · сеть {self.network}"


# Пусто — блока на экране нет. Формат и контрольные суммы сверяет tests/test_support_view.py.
WALLETS: tuple[Wallet, ...] = (
    Wallet("USDT", "Tron (TRC-20)", "TCzGTzjcLjGa4xckJGktiJBpZ9hoMJ9Q3J"),
    Wallet("BTC", "Bitcoin", "bc1q9a3wtdkmkwu93chk6tltzz5h0ysnlhns8p8cds"),
    Wallet("SOL", "Solana", "DBoHF7TMggDNHBX7sbYx8qtcvxZ4fRskDSGqoABA3TJK"),
)
