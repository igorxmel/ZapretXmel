"""Сайта проекта больше нет, а публичные тексты описывают программу, а не агитируют.

Правило и причина — в AGENTS.md, раздел «Публичные тексты». Проверка нужна потому, что
старая ссылка или лозунг возвращаются незаметно: достаточно скопировать абзац из истории.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ("README.md", "FAQ.md", "SECURITY.md", "CONTRIBUTING.md", "THIRD-PARTY.md")


def _sources() -> list[Path]:
    return [*(ROOT / name for name in DOCUMENTS), *(ROOT / "app").rglob("*.py")]


@pytest.mark.parametrize(
    "phrase",
    ["github.io/ZapretXmel", "Свободный интернет", "Обход блокировок в одном окне"],
)
def test_phrase_is_gone(phrase: str) -> None:
    offenders = [path.name for path in _sources() if phrase in path.read_text(encoding="utf-8")]

    assert offenders == []


def test_readers_are_told_there_is_no_site() -> None:
    """Иначе подделка под официальный сайт выглядела бы правдоподобно."""
    for name in ("README.md", "SECURITY.md"):
        text = (ROOT / name).read_text(encoding="utf-8")

        assert "подделка" in text and "не будет" in text


def test_site_folder_is_gone() -> None:
    assert not (ROOT / "docs").exists()


def test_title_bar_has_only_official_places() -> None:
    """Официальных мест два: репозиторий и форум. Третья ссылка — уже чужая."""
    from app.core import guide
    from app.ui.frameless import LINKS

    assert LINKS == (
        ("ФОРУМ", guide.FORUM_URL),
        ("GITHUB", "https://github.com/igorxmel/ZapretXmel"),
    )


def test_readme_pictures_exist() -> None:
    """Снимки лежали в папке сайта и уехали оттуда: битая картинка сама не напомнит."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pictures = [part.split('"')[0] for part in readme.split('="media/')[1:]]

    assert pictures
    for name in pictures:
        assert (ROOT / "media" / name).is_file(), name

def _readme_wallet_block() -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    start = readme.index("### Поддержать проект")
    end = readme.index("\n## ", start)
    return readme[start:end]


def test_readme_wallets_match_the_program() -> None:
    """Адреса в README и в программе — один и тот же набор, буква в букву.

    Кошельки в двух местах — решение автора. Опасность в том, что одно место поправят,
    а другое нет, или подменят адрес только в README: тогда деньги уйдут чужому, и никто
    не заметит. Поэтому сверяем каждое изменение.
    """
    from app.core import donate

    block = _readme_wallet_block()
    shown = re.findall(r"`([^`]+)`", block)

    assert shown == [wallet.address for wallet in donate.WALLETS]
    for wallet in donate.WALLETS:
        assert wallet.network in block, f"{wallet.coin}: в README не названа сеть"


def test_readme_coin_icons_exist() -> None:
    block = _readme_wallet_block()
    icons = re.findall(r'src="(assets/icons/coin-[a-z]+\.svg)"', block)

    assert icons
    for icon in icons:
        assert (ROOT / icon).is_file(), icon


def test_forum_link_is_the_same_everywhere() -> None:
    """Форум в Telegram — второе официальное место. Чужая ссылка, подменённая в одном
    файле, уводила бы людей в поддельный чат."""
    from app.core import guide

    for name in ("README.md", "SECURITY.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        links = set(re.findall(r"https://t\.me/[A-Za-z0-9_]+", text))
        assert links == {guide.FORUM_URL}, name
