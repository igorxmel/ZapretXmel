"""Текст справки: короткие шаги и частые вопросы из FAQ.md.

Большой гайд по всем кнопкам устаревал бы с каждой версией, а открыли бы его не те,
кому он нужен. Поэтому здесь только порядок действий, а ответы берутся из того же
файла, что на сайте и в README. FAQ едет внутри сборки, сеть для справки не нужна.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core import paths

log = logging.getLogger(__name__)

FAQ_FILENAME = "FAQ.md"

# Шаги и советы по отдельности: окно справки рисует каждый шаг своей строкой с номером.
STEP_ITEMS: tuple[tuple[str, str], ...] = (
    (
        "Выключите VPN",
        "Пока он работает, обход ни на что не влияет, а проверки меряют VPN.",
    ),
    (
        "Подберите стратегию",
        "Раздел «Подбор стратегии» → «Запустить подбор». У каждого провайдера работает своя, "
        "поэтому подбор занимает несколько минут.",
    ),
    (
        "Включите её",
        "Нажмите «Применить лучшую». Если выбираете сами, то в списке выберите стратегию и "
        "нажмите «Применить и включить»: просто выбрать в списке недостаточно.",
    ),
    (
        "Проверьте",
        "Кнопка «Проверить, работает ли сейчас» покажет, какие сервисы открываются, и напишет, "
        "какая стратегия проверена.",
    ),
    (
        "Перестало работать?",
        "Запустите подбор снова. Блокировки меняются без предупреждения, и лучшая стратегия "
        "может отвалиться уже через час.",
    ),
)

TIPS: tuple[tuple[str, str], ...] = (
    (
        "Telegram",
        "Чинится отдельно: стратегии ему не помогают. Включите правую кнопку и один раз добавьте "
        "прокси в сам Telegram, кнопкой «Открыть в Telegram» на вкладке Telegram.",
    ),
    (
        "Мини-окно",
        "Кнопка со стрелками слева вверху оставляет только главные кнопки, список стратегий и "
        "проверку. Всё остальное спрятано в меню «Все разделы» внизу окна.",
    ),
)

STEPS = "## С чего начать\n\n" + "".join(
    f"{number}. **{title}.** {text}\n" if not title.endswith("?") else
    f"{number}. **{title}** {text}\n"
    for number, (title, text) in enumerate(STEP_ITEMS, 1)
) + "".join(f"\n**{title}.** {text}\n" for title, text in TIPS)

ASK_URL = "https://github.com/igorxmel/ZapretXmel/issues"

# Форум проекта в Telegram: вопросы, помощь с настройкой, обмен стратегиями. Ссылка одна
# на всю программу — README и SECURITY.md сверяются с ней тестом.
FORUM_URL = "https://t.me/XmelNet"

def faq_file() -> Path:
    """Где лежит FAQ: в сборке рядом с картинками, в исходниках в корне проекта."""
    packed = paths.assets_dir() / FAQ_FILENAME
    return packed if packed.is_file() else paths.app_root() / FAQ_FILENAME


def faq_markdown() -> str:
    """Вопросы без служебного заголовка и пометок для разработчика."""
    try:
        text = faq_file().read_text(encoding="utf-8")
    except OSError:
        log.info("Файл с вопросами не найден: %s", faq_file())
        return ""

    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    first_question = text.find("\n## ")
    return text[first_question + 1 :].strip() if first_question >= 0 else text.strip()


def help_markdown() -> str:
    """Весь текст окна справки. Без файла с вопросами остаются хотя бы шаги."""
    faq = faq_markdown()
    return f"{STEPS}\n# Частые вопросы\n\n{faq}" if faq else STEPS


def faq_items() -> list[tuple[str, str]]:
    """Вопросы по одному: заголовок и ответ в разметке."""
    items = []
    for part in re.split(r"^## ", faq_markdown(), flags=re.MULTILINE):
        part = part.strip()
        if not part:
            continue
        question, _, answer = part.partition("\n")
        items.append((question.strip(), answer.strip()))
    return items
