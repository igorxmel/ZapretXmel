"""Частые вопросы живут в трёх местах и обязаны совпадать.

Полный текст — в `FAQ.md` и на сайте, оглавление со ссылками — в README. Дублируются
они намеренно: README читают на GitHub, сайт открывают те, кто туда не заглядывает.
Но копии расходятся молча: поправили одну, забыли другую — и люди получают разные
ответы на один вопрос. Проверяются вопросы, а не весь текст: формат у копий разный,
а набор и порядок вопросов должны быть одни и те же.
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
    end = text.index("\n## ", start)
    return re.findall(r"^- \[(.+?)\]\(FAQ\.md#", text[start:end], re.MULTILINE)


def site_questions() -> list[str]:
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    start = page.index('<section class="faq')
    end = page.index("</section>", start)
    return re.findall(r"<summary>(.*?)</summary>", page[start:end])


def anchor(title: str) -> str:
    """Якорь заголовка по правилам GitHub: строчные, без знаков, пробел → дефис."""
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", title.lower()).strip())


def test_all_three_copies_ask_the_same_questions_in_the_same_order() -> None:
    assert faq_questions() == readme_questions() == site_questions()


def test_the_list_is_not_empty() -> None:
    """Пустые списки тоже «совпадают» — этот тест не даёт потерять все копии разом."""
    assert len(faq_questions()) >= 4


def test_the_questions_the_owner_asked_for_are_there() -> None:
    questions = " ".join(faq_questions())

    assert "Что такое ZapretXmel" in questions
    assert "Это VPN" in questions
    assert "не работает" in questions


def test_readme_links_point_at_the_real_headings() -> None:
    """Ссылка с неверным якорем открывает файл с начала и выглядит рабочей."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\(FAQ\.md#(.+?)\)", text)

    assert links == [anchor(question) for question in faq_questions()]


def test_site_has_the_anchor_the_faq_file_links_to() -> None:
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    faq = (ROOT / "FAQ.md").read_text(encoding="utf-8")

    assert 'id="faq"' in page
    assert "/#faq" in faq


def test_site_answers_carry_no_raw_markdown() -> None:
    """Сайт получает HTML из той же разметки: звёздочки и обратные кавычки не должны просочиться."""
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    block = page[page.index('<section class="faq'):]
    block = block[: block.index("</section>")]

    assert "**" not in block
    assert "`" not in block
