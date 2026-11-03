"""Экран поддержки. Нужен QApplication.

Самое важное: без адресов блока нет, а адрес копируется точно, символ в символ.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from app.core import donate
from app.core.config import Settings
from app.ui.controller import Controller
from app.ui.views.support import SupportView, WalletRow

ROOT = Path(__file__).resolve().parents[1]
WALLET = donate.Wallet("USDT", "TRC-20", "TTestAddress000000000000000000000")


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_no_addresses_means_no_block(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(donate, "WALLETS", ())

    assert SupportView(Controller(Settings())).wallet_rows == []


def test_addresses_are_shown(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(donate, "WALLETS", (WALLET,))

    rows = SupportView(Controller(Settings())).wallet_rows

    assert [row.wallet for row in rows] == [WALLET]


def test_copy_gives_the_exact_address(app: QApplication) -> None:
    row = WalletRow(WALLET)

    row.copy_button.click()

    assert QApplication.clipboard().text() == WALLET.address
    assert row.copy_button.text() == "Скопировано"


def test_network_is_always_named() -> None:
    """Перевод в другой сети может пропасть, а отменить его нельзя."""
    assert "TRC-20" in WALLET.title


def test_supporters_list_is_gone() -> None:
    assert not (ROOT / "supporters.json").exists()
    assert not (ROOT / "app" / "core" / "supporters.py").exists()
