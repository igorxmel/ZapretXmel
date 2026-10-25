"""Частые вопросы живут в двух местах — в README и на сайте — и обязаны совпадать.

Дублируются они намеренно: README читают на GitHub, сайт открывают те, кто туда не
заглядывает. Но две копии расходятся молча: поправили одну, забыли вторую — и
люди получают разные ответы на один вопрос. Проверяются вопросы, а не весь текст:
формат у копий разный, а набор и порядок вопросов должны быть одни и те же.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def readme_questions() -> list[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("Частые вопросы")
    end = text.index("\n## ", start)
    return re.findall(r"<summary><b>(.*?)</b></summary>", text[start:end])


def site_questions() -> list[str]:
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    start = page.index('<section class="faq')
    end = page.index("</section>", start)
    return re.findall(r"<summary>(.*?)</summary>", page[start:end])


def test_the_two_copies_ask_the_same_questions_in_the_same_order() -> None:
    assert readme_questions() == site_questions()


def test_the_list_is_not_empty() -> None:
    """Пустой список тоже «совпадает» — этот тест не даёт потерять оба разом."""
    assert len(readme_questions()) >= 4


def test_the_questions_the_owner_asked_for_are_there() -> None:
    questions = " ".join(readme_questions())

    assert "Что такое ZapretXmel" in questions
    assert "Это VPN" in questions
    assert "не работает" in questions


def test_site_answers_carry_no_raw_markdown() -> None:
    """Сайт получает HTML из той же разметки: звёздочки и обратные кавычки не должны просочиться."""
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    block = page[page.index('<section class="faq'):]
    block = block[: block.index("</section>")]

    assert "**" not in block
    assert "`" not in block
