"""Тесты слоя ИИ-диагностики.

Проверяется то, что ломается тихо: вычистка личных данных из снимка, разбор
ответа модели в произвольной обёртке и состав выгружаемого пакета.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.core.diagnostics import ai, bundle
from app.core.diagnostics.ai import Analysis, parse_answer, provider_by_id
from app.core.diagnostics.snapshot import REDACTED, problems_only, sanitize

# --- вычистка личных данных ---------------------------------------------


def test_username_is_removed_from_paths() -> None:
    result = sanitize(r"C:\Users\petya\AppData\app.log", user="petya")

    assert "petya" not in result
    assert REDACTED in result


def test_username_is_matched_whole_only() -> None:
    """Короткое имя иначе срабатывает внутри обычных слов и портит путь."""
    result = sanitize(r"C:\Users\user\AppData", user="user")

    assert r"C:\Users" in result, "слово Users не должно пострадать"


def test_public_addresses_are_hidden() -> None:
    assert REDACTED in sanitize("внешний 203.0.113.7", user="x")


def test_private_addresses_are_kept() -> None:
    """По ним видно, что трафик уходит в туннель, а выдать они ничего не могут."""
    text = sanitize("локальный 192.168.1.50, туннель 10.8.1.2, свой 127.0.0.1", user="x")

    assert "192.168.1.50" in text
    assert "10.8.1.2" in text
    assert "127.0.0.1" in text


def test_mac_addresses_are_hidden() -> None:
    assert REDACTED in sanitize("адаптер e0:d5:5e:a2:63:be", user="x")


def test_nested_structures_are_cleaned() -> None:
    data = {"а": ["203.0.113.7", {"б": "203.0.113.8"}], "число": 7}

    result = sanitize(data, user="x")

    assert result["а"][0] == REDACTED
    assert result["а"][1]["б"] == REDACTED
    assert result["число"] == 7, "числа трогать не нужно"


def test_short_username_is_ignored() -> None:
    """Имя в два символа встречается всюду — по нему чистить опаснее, чем не чистить."""
    assert sanitize("ab cd ab", user="ab") == "ab cd ab"


def test_problems_only_keeps_important() -> None:
    snapshot = {
        "находки": [
            {"важность": "error", "что": "Нет BFE", "подробности": "служба стоит"},
            {"важность": "ok", "что": "Всё хорошо", "подробности": ""},
            {"важность": "warning", "что": "Прокси", "подробности": ""},
        ]
    }

    problems = problems_only(snapshot)

    assert len(problems) == 2
    assert "Нет BFE" in problems[0]


# --- разбор ответа модели -----------------------------------------------


def test_clean_json_is_parsed() -> None:
    answer = parse_answer('{"verdict":"Сломана служба","cause":"BFE","steps":["Запустить"]}')

    assert answer.verdict == "Сломана служба"
    assert answer.cause == "BFE"
    assert answer.steps == ["Запустить"]


def test_json_in_code_fence_is_parsed() -> None:
    """Модели охотно оборачивают ответ в тройные кавычки."""
    answer = parse_answer('```json\n{"verdict":"ок","steps":["раз","два"]}\n```')

    assert answer.verdict == "ок"
    assert answer.steps == ["раз", "два"]


def test_json_surrounded_by_text_is_parsed() -> None:
    answer = parse_answer('Вот разбор: {"verdict":"ок","steps":["раз"]} надеюсь помог')

    assert answer.verdict == "ок"


def test_steps_as_single_string_become_a_list() -> None:
    answer = parse_answer('{"verdict":"ок","steps":"сделать одно"}')

    assert answer.steps == ["сделать одно"]


def test_unparseable_answer_is_kept_as_is() -> None:
    """Показать сырой ответ лучше, чем пустоту."""
    answer = parse_answer("не смог разобрать")

    assert answer.raw == "не смог разобрать"
    assert answer.verdict


def test_empty_steps_are_dropped() -> None:
    answer = parse_answer('{"verdict":"ок","steps":["дело","","   "]}')

    assert answer.steps == ["дело"]


def test_analysis_renders_readable_text() -> None:
    text = Analysis(
        verdict="Служба стоит", cause="BFE выключена", steps=["Раз", "Два"], confidence="высокая"
    ).as_text()

    assert "Служба стоит" in text
    assert "1. Раз" in text
    assert "2. Два" in text
    assert "высокая" in text


def test_empty_analysis_is_detected() -> None:
    assert Analysis().is_empty
    assert not Analysis(verdict="есть").is_empty


# --- провайдеры ----------------------------------------------------------


def test_every_provider_has_models_and_key_page() -> None:
    for provider in ai.PROVIDERS:
        assert provider.models, provider.id
        assert provider.key_url.startswith("https://"), provider.id
        assert provider.default_model == provider.models[0]


def test_claude_is_first_and_uses_current_model() -> None:
    assert ai.PROVIDERS[0].id == "anthropic"
    assert ai.PROVIDERS[0].default_model == "claude-opus-5-5"


def test_unknown_provider_is_rejected() -> None:
    assert provider_by_id("нет такого") is None

    with pytest.raises(ai.AiError):
        ai.analyze({}, "", "нет такого")


def test_analyze_without_key_explains_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai.secrets, "load", lambda name: "")

    with pytest.raises(ai.AiError, match="ключ"):
        ai.analyze({}, "", "anthropic")


# --- пакет для внешнего ИИ ----------------------------------------------


def test_prompt_mentions_problem_and_findings() -> None:
    snapshot = {"находки": [{"важность": "error", "что": "Нет BFE", "подробности": ""}]}

    prompt = bundle.build_prompt(snapshot, "Discord не работает")

    assert "Discord не работает" in prompt
    assert "Нет BFE" in prompt
    assert bundle.GUIDE_NAME in prompt


def test_prompt_handles_missing_problem() -> None:
    prompt = bundle.build_prompt({"находки": []}, "")

    assert "не описана" in prompt
    assert "ничего подозрительного" in prompt


def test_guide_explains_the_traps() -> None:
    """Без пояснения нейросеть советует наугад — проверяем ключевые предупреждения."""
    assert "VPN" in bundle.GUIDE
    assert "UDP" in bundle.GUIDE
    assert "без обхода" in bundle.GUIDE


def test_bundle_contains_everything_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        bundle.snapshot_module, "build", lambda sanitized=True: {"находки": [], "проба": 1}
    )
    monkeypatch.setattr(bundle.paths, "logs_dir", lambda: tmp_path / "нет")
    monkeypatch.setattr(bundle.paths, "history_dir", lambda: tmp_path / "нет")

    path = bundle.export("проблема", destination=tmp_path)

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert bundle.SNAPSHOT_NAME in names
        assert bundle.GUIDE_NAME in names
        assert bundle.PROMPT_NAME in names
        assert json.loads(archive.read(bundle.SNAPSHOT_NAME))["проба"] == 1
