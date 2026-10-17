"""Разбор неполадки нейросетью.

Поверх детерминированных правил, которые работают всегда и без сети. Правила
ловят известное — конфликт служб, выключенный BFE, активный туннель; нейросеть
нужна для случаев, которых в правилах нет: странный лог, непонятное сочетание
настроек, вопрос «а почему именно так».

Провайдер подключаемый. Claude вызывается официальным SDK; остальные — своими
HTTP-интерфейсами. Ответ запрашивается в виде JSON и разбирается с запасом на
то, что модель обернёт его в текст или в тройные кавычки: просить строгий
формат у пяти разных сервисов пришлось бы пятью разными способами, а
проверить разобранное — одним.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import requests

from app.core.diagnostics import bundle, secrets

log = logging.getLogger(__name__)

TIMEOUT = 120
MAX_TOKENS = 4000

SYSTEM_PROMPT = (
    "Ты помогаешь разобраться, почему на компьютере с Windows не работает обход "
    "блокировок zapret. Отвечай по-русски, по делу, без вступлений и извинений.\n\n"
    "Верни ТОЛЬКО объект JSON, без пояснений вокруг, с полями:\n"
    '  "verdict" — вердикт одной фразой;\n'
    '  "cause" — вероятная причина со ссылкой на конкретные поля снимка;\n'
    '  "steps" — массив строк: что сделать, по порядку, от вероятного к запасному;\n'
    '  "confidence" — "высокая", "средняя" или "низкая".\n\n'
    "Если данных не хватает, скажи это в cause и поставь низкую уверенность. "
    "Не предлагай VPN: человек пользуется обходом именно чтобы обойтись без него. "
    "Не выдумывай названия стратегий — бери только те, что есть в снимке."
)


@dataclass(frozen=True)
class Provider:
    """Описание сервиса, который умеет разбирать неполадку."""

    id: str
    label: str
    kind: str
    models: tuple[str, ...]
    key_url: str
    note: str = ""

    @property
    def default_model(self) -> str:
        return self.models[0]


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        id="anthropic",
        label="Claude",
        kind="anthropic",
        models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
        key_url="https://console.anthropic.com/settings/keys",
        note="Разбирает лучше всех, но запросы платные.",
    ),
    Provider(
        id="groq",
        label="Groq",
        kind="openai",
        models=("llama-3.3-70b-versatile",),
        key_url="https://console.groq.com/keys",
        note="Бесплатный уровень с ограничением числа запросов.",
    ),
    Provider(
        id="openrouter",
        label="OpenRouter",
        kind="openai",
        models=("deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct"),
        key_url="https://openrouter.ai/keys",
        note="Есть бесплатные модели, выбор широкий.",
    ),
    Provider(
        id="mistral",
        label="Mistral AI",
        kind="openai",
        models=("mistral-large-latest", "mistral-small-latest"),
        key_url="https://console.mistral.ai/api-keys",
        note="Европейский сервис, есть бесплатный уровень.",
    ),
    Provider(
        id="gemini",
        label="Google Gemini",
        kind="gemini",
        models=("gemini-2.0-flash",),
        key_url="https://aistudio.google.com/apikey",
        note="Бесплатный уровень без привязки карты.",
    ),
)

ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "mistral": "https://api.mistral.ai/v1/chat/completions",
}

USER_AGENT = "ZapretXmel"
# Версия API Anthropic: у них она передаётся заголовком и обязательна.
ANTHROPIC_VERSION = "2023-06-01"

# Откуда спрашивать список доступных моделей. Зашитые имена протухают
# молча: сервисы снимают модели с обслуживания, и разбор начинает отвечать
# «404» вместо ответа. Списки в PROVIDERS остаются запасным вариантом на
# случай, когда спросить не удалось.
MODEL_LISTS = {
    "groq": "https://api.groq.com/openai/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
}


class AiError(Exception):
    """Запрос к нейросети не удался."""


@dataclass
class Analysis:
    """Разбор, полученный от нейросети."""

    verdict: str = ""
    cause: str = ""
    steps: list[str] = field(default_factory=list)
    confidence: str = ""
    provider: str = ""
    model: str = ""
    raw: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.verdict or self.cause or self.steps)

    def as_text(self) -> str:
        lines = [self.verdict or "Вердикт не получен"]
        if self.cause:
            lines += ["", f"Причина: {self.cause}"]
        if self.steps:
            lines += ["", "Что сделать:"]
            lines += [f"{number}. {step}" for number, step in enumerate(self.steps, start=1)]
        if self.confidence:
            lines += ["", f"Уверенность: {self.confidence}"]
        return "\n".join(lines)


def provider_by_id(provider_id: str) -> Provider | None:
    return next((item for item in PROVIDERS if item.id == provider_id), None)


def key_name(provider_id: str) -> str:
    return f"ai.{provider_id}"


def has_key(provider_id: str) -> bool:
    return secrets.has(key_name(provider_id))


def parse_answer(text: str) -> Analysis:
    """Достаёт разбор из ответа модели.

    Модели охотно оборачивают JSON в пояснения и тройные кавычки, поэтому
    сначала вырезается сам объект, и только потом разбирается.
    """
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()

    data: dict = {}
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        if match := re.search(r"\{.*\}", cleaned, re.DOTALL):
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                data = {}

    if not isinstance(data, dict) or not data:
        # Ответ не разобрался — показываем как есть, это лучше пустоты.
        return Analysis(verdict="Ответ получен, но не в ожидаемом виде", raw=text)

    steps = data.get("steps") or []
    if isinstance(steps, str):
        steps = [steps]

    return Analysis(
        verdict=str(data.get("verdict", "")).strip(),
        cause=str(data.get("cause", "")).strip(),
        steps=[str(step).strip() for step in steps if str(step).strip()],
        confidence=str(data.get("confidence", "")).strip(),
        raw=text,
    )


def _build_question(snapshot: dict, problem: str) -> str:
    return (
        f"{bundle.build_prompt(snapshot, problem)}\n\n"
        "Снимок состояния:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, indent=2)}"
    )


def _ask_anthropic(provider: Provider, model: str, key: str, question: str) -> str:
    try:
        import anthropic
    except ImportError as error:
        raise AiError(
            "не установлен пакет anthropic — выполните: "
            '.venv\\Scripts\\pip install "anthropic"'
        ) from error

    client = anthropic.Anthropic(api_key=key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
    except anthropic.AuthenticationError as error:
        raise AiError("ключ не принят — проверьте его в настройках") from error
    except anthropic.RateLimitError as error:
        raise AiError("слишком часто: сервис ограничил число запросов") from error
    except anthropic.APIStatusError as error:
        raise AiError(f"сервис ответил ошибкой {error.status_code}") from error
    except anthropic.APIConnectionError as error:
        raise AiError("не удалось связаться с сервисом — проверьте сеть") from error

    if response.stop_reason == "refusal":
        raise AiError("модель отказалась отвечать на этот запрос")

    return "".join(block.text for block in response.content if block.type == "text")


def _ask_openai_compatible(provider: Provider, model: str, key: str, question: str) -> str:
    endpoint = ENDPOINTS.get(provider.id)
    if not endpoint:
        raise AiError(f"для {provider.label} не задан адрес сервиса")

    response = requests.post(
        endpoint,
        timeout=TIMEOUT,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        },
    )
    _raise_for_status(response, provider)

    try:
        return response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as error:
        raise AiError(f"{provider.label} вернул ответ неожиданного вида") from error


def _ask_gemini(provider: Provider, model: str, key: str, question: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    response = requests.post(
        url,
        timeout=TIMEOUT,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": question}]}],
            "generationConfig": {"maxOutputTokens": MAX_TOKENS},
        },
    )
    _raise_for_status(response, provider)

    try:
        parts = response.json()["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError, ValueError) as error:
        raise AiError(f"{provider.label} вернул ответ неожиданного вида") from error


def _raise_for_status(response: requests.Response, provider: Provider) -> None:
    if response.ok:
        return
    if response.status_code in (401, 403):
        raise AiError("ключ не принят — проверьте его в настройках")
    if response.status_code == 429:
        raise AiError("слишком часто: сервис ограничил число запросов")
    if response.status_code == 404:
        # Самая частая причина: сервис снял модель с обслуживания. Писать
        # голое «404» бесполезно — человек идёт проверять интернет.
        raise AiError(
            f"{provider.label} не знает такой модели — скорее всего её сняли "
            "с обслуживания. Нажмите «Обновить список» и выберите другую."
        )
    raise AiError(f"{provider.label} ответил ошибкой {response.status_code}")


def list_models(provider: Provider, key: str, timeout: int = 20) -> list[str]:
    """Спрашивает у сервиса, какие модели у него есть сейчас.

    Зашитый список — не источник правды: сервисы снимают модели, и разбор
    начинает отвечать «404». Не ответил или ответил непонятно — остаётся
    запасной список, он всё же лучше пустого выбора.
    """
    url = MODEL_LISTS.get(provider.id)
    if not url:
        return list(provider.models)

    headers = {"User-Agent": USER_AGENT}
    params = {}
    if provider.kind == "anthropic":
        headers |= {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    elif provider.kind == "gemini":
        params["key"] = key
    else:
        headers["Authorization"] = f"Bearer {key}"

    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        _raise_for_status(response, provider)
        payload = response.json()
    except AiError:
        raise
    except Exception as error:  # noqa: BLE001 — сеть может не ответить
        raise AiError(f"не удалось получить список моделей: {error}") from error

    items = payload.get("data") or payload.get("models") or []
    names = []
    for item in items:
        name = item.get("id") or item.get("name") or ""
        # Gemini отдаёт «models/gemini-2.5-flash» — показываем без приставки.
        names.append(str(name).removeprefix("models/"))

    return sorted(name for name in names if name) or list(provider.models)


def analyze(snapshot: dict, problem: str, provider_id: str, model: str = "") -> Analysis:
    """Отправляет снимок выбранному сервису и возвращает разбор."""
    provider = provider_by_id(provider_id)
    if provider is None:
        raise AiError(f"неизвестный сервис: {provider_id}")

    key = secrets.load(key_name(provider_id))
    if not key:
        raise AiError(f"для {provider.label} не сохранён ключ")

    model = model or provider.default_model
    question = _build_question(snapshot, problem)

    log.info("Запрашиваю разбор у %s (%s)", provider.label, model)
    try:
        if provider.kind == "anthropic":
            answer = _ask_anthropic(provider, model, key, question)
        elif provider.kind == "gemini":
            answer = _ask_gemini(provider, model, key, question)
        else:
            answer = _ask_openai_compatible(provider, model, key, question)
    except requests.RequestException as error:
        raise AiError("не удалось связаться с сервисом — проверьте сеть") from error

    analysis = parse_answer(answer)
    analysis.provider = provider.label
    analysis.model = model
    return analysis
