"""Частые вопросы живут в двух местах и обязаны совпадать.

Полный текст — в `FAQ.md`, оглавление со ссылками — в README. Копии расходятся молча:
поправили одну, забыли другую. Проверяются вопросы, а не весь текст.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def faq_questions() -> list[str]:
    text = (ROOT / "FAQ.md").read_text(encoding="utf-8")
    return re.findall(r"^## (.+)$", text, re.MULTILINE)


def readme_questions() -> list[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("Частые вопросы")
    return re.findall(r"^- \[(.+?)\]\(FAQ\.md#", text[start:], re.MULTILINE)


def anchor(title: str) -> str:
    """Якорь заголовка по правилам GitHub: строчные, без знаков, пробел → дефис."""
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", title.lower()).strip())


def test_both_copies_ask_the_same_questions_in_the_same_order() -> None:
    assert faq_questions() == readme_questions()


def test_the_list_is_not_empty() -> None:
    """Пустые списки тоже «совпадают» — этот тест не даёт потерять все копии разом."""
    assert len(faq_questions()) >= 4


def test_the_questions_the_owner_asked_for_are_there() -> None:
    questions = " ".join(faq_questions())

    assert "Что такое ZapretXmel" in questions
    assert "Это VPN" in questions
    assert "не открывается" in questions


def test_readme_links_point_at_the_real_headings() -> None:
    """Ссылка с неверным якорем открывает файл с начала и выглядит рабочей."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\(FAQ\.md#(.+?)\)", text)

    assert links == [anchor(question) for question in faq_questions()]
