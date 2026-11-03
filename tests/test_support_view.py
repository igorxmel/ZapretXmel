"""Экран поддержки. Нужен QApplication.

Самое важное: без адресов блока нет, а адрес копируется точно, символ в символ.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from app.core import donate
from app.core.config import Settings
from app.core.updater import github
from app.ui.controller import Controller
from app.ui.views import support
from app.ui.views.support import REPO_URL, SupportView, WalletRow

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


# --- настоящие адреса: опечатка в них отправила бы деньги в никуда -----------

BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _base58(text: str) -> bytes:
    number = 0
    for char in text:
        number = number * 58 + BASE58.index(char)
    zeros = len(text) - len(text.lstrip("1"))
    return b"\0" * zeros + number.to_bytes((number.bit_length() + 7) // 8, "big")


def _tron_is_valid(address: str) -> bool:
    raw = _base58(address)
    digest = hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()
    return len(raw) == 25 and raw[0] == 0x41 and digest[:4] == raw[-4:]


def _bech32_is_valid(address: str) -> bool:
    prefix, _, data = address.rpartition("1")
    values = [BECH32.index(char) for char in data]
    expanded = [ord(c) >> 5 for c in prefix] + [0] + [ord(c) & 31 for c in prefix]
    check = 1
    for value in expanded + values:
        top = check >> 25
        check = (check & 0x1FFFFFF) << 5 ^ value
        for bit, generator in enumerate(
            (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
        ):
            check ^= generator if (top >> bit) & 1 else 0
    return prefix == "bc" and check == 1


def _by_coin(coin: str) -> str:
    return next(wallet.address for wallet in donate.WALLETS if wallet.coin == coin)


def test_tron_address_passes_its_checksum() -> None:
    assert _tron_is_valid(_by_coin("USDT"))


def test_bitcoin_address_passes_its_checksum() -> None:
    assert _bech32_is_valid(_by_coin("BTC"))


def test_solana_address_is_a_32_byte_key() -> None:
    """У адреса Solana контрольной суммы нет: проверить можно только формат."""
    assert len(_base58(_by_coin("SOL"))) == 32


@pytest.mark.parametrize(
    ("check", "address"),
    [
        (_tron_is_valid, "TCzGTzjcLjGa4xckJGktiJBpZ9hoMJ9Q3K"),
        (_bech32_is_valid, "bc1q9a3wtdkmkwu93chk6tltzz5h0ysnlhns8p8cdq"),
    ],
)
def test_checks_catch_a_typo(check, address: str) -> None:
    """Иначе проверки выше ничего не доказывают."""
    assert not check(address)


def test_every_wallet_names_its_network() -> None:
    assert {wallet.coin for wallet in donate.WALLETS} == {"USDT", "BTC", "SOL"}
    assert all(wallet.network for wallet in donate.WALLETS)


# --- звёзды и просьба поделиться ----------------------------------------------


class _Answer:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self.headers = {}
        self.text = text
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise github.requests.HTTPError(str(self.status_code))

    def json(self):
        return self._body


@pytest.mark.parametrize(
    ("answer", "stars"),
    [
        (_Answer(body={"stargazers_count": 12}), 12),
        (_Answer(403, text="API rate limit exceeded"), None),
        (_Answer(500), None),
        (_Answer(body={"message": "нет такого поля"}), None),
    ],
)
def test_stars_never_raise(monkeypatch: pytest.MonkeyPatch, answer: _Answer, stars) -> None:
    monkeypatch.setattr(github.requests, "get", lambda *_, **__: answer)

    assert github.repo_stars("o/r") == stars


def test_stars_survive_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_, **__):
        raise github.requests.ConnectionError("нет сети")

    monkeypatch.setattr(github.requests, "get", broken)

    assert github.repo_stars("o/r") is None


@pytest.fixture
def view(app: QApplication) -> SupportView:
    return SupportView(Controller(Settings()))


def _stars_text(view: SupportView) -> str:
    return view._stars._value.text()


def test_star_count_is_shown(view: SupportView) -> None:
    view._show_stars(12)

    assert _stars_text(view) == "12"


def test_failed_answer_keeps_the_last_count(view: SupportView) -> None:
    view._show_stars(12)
    view._show_stars(None)

    assert _stars_text(view) == "12"


def test_count_is_a_dash_until_known(view: SupportView) -> None:
    assert _stars_text(view) == "—"


def test_share_button_copies_the_repository_link(view: SupportView) -> None:
    view.share_button.click()

    assert QApplication.clipboard().text() == REPO_URL
    assert view.share_button.text() == "Ссылка скопирована"


def test_stars_are_not_asked_on_every_opening(
    view: SupportView, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Лимит GitHub общий на адрес, а экран открывают сколько угодно раз."""
    asked: list[bool] = []

    class FakeTask:
        def __init__(self, *_):
            asked.append(True)
            self.done = self

        def connect(self, _slot):
            pass

        def start(self):
            pass

        def isRunning(self):  # noqa: N802 — имя задано Qt
            return False

    monkeypatch.setattr(support, "Task", FakeTask)

    view.reload()
    view.reload()

    assert asked == [True]
