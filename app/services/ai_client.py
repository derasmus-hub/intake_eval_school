"""Centralized AI client supporting OpenAI and Anthropic.

Usage:
    from app.services.ai_client import ai_chat

    result = await ai_chat(
        messages=[
            {"role": "system", "content": "You are a helpful tutor."},
            {"role": "user", "content": "Explain present perfect."},
        ],
        use_case="lesson",       # "lesson", "assessment", "cheap", or None for default
        temperature=0.7,
        json_mode=True,
    )
    # result is the text content of the assistant response

Provider is auto-detected per use case from the model name:
  - Models starting with "claude-" route to Anthropic
  - Everything else routes to OpenAI
This lets you mix providers, e.g. LESSON_MODEL=claude-sonnet-4-20250514
and CHEAP_MODEL=gpt-4o-mini simultaneously.
"""

import logging
from enum import Enum

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings

logger = logging.getLogger(__name__)


class AIProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


# Known Anthropic model prefixes for auto-detection
_ANTHROPIC_PREFIXES = ("claude-",)


def _resolve_model(use_case: str | None) -> str:
    """Pick the model name based on the use case and config overrides."""
    if use_case == "lesson" and settings.lesson_model:
        return settings.lesson_model
    if use_case == "assessment" and settings.assessment_model:
        return settings.assessment_model
    if use_case == "cheap" and settings.cheap_model:
        return settings.cheap_model
    return settings.model_name


def _detect_provider(model: str) -> AIProvider:
    """Auto-detect the provider from the model name.

    Models starting with 'claude-' are routed to Anthropic.
    Everything else uses the global ai_provider setting (default: OpenAI).
    """
    model_lower = model.lower()
    for prefix in _ANTHROPIC_PREFIXES:
        if model_lower.startswith(prefix):
            return AIProvider.ANTHROPIC
    # For non-Claude models, check if the global default is Anthropic
    # (supports custom/fine-tuned Anthropic model names)
    try:
        return AIProvider(settings.ai_provider.lower())
    except ValueError:
        return AIProvider.OPENAI


async def ai_chat(
    messages: list[dict],
    *,
    use_case: str | None = None,
    temperature: float = 0.7,
    json_mode: bool = False,
    max_tokens: int = 4096,
) -> str:
    """Send a chat completion and return the assistant text.

    Works with both OpenAI and Anthropic APIs transparently.
    Provider is auto-detected from the resolved model name, so you can
    mix providers per use case (e.g. Claude for lessons, GPT for cheap).
    All API keys are read from settings (loaded from .env at startup).
    """
    model = _resolve_model(use_case)
    provider = _detect_provider(model)

    if provider == AIProvider.OPENAI:
        return await _openai_chat(messages, model, temperature, json_mode, max_tokens)
    elif provider == AIProvider.ANTHROPIC:
        return await _anthropic_chat(messages, model, temperature, json_mode, max_tokens)
    else:
        raise ValueError(f"Unknown AI provider: {provider}")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(Exception),
    before_sleep=lambda retry_state: logger.warning(
        "OpenAI call failed (attempt %d), retrying: %s",
        retry_state.attempt_number,
        retry_state.outcome.exception(),
    ),
    reraise=True,
)
async def _openai_chat(
    messages: list[dict],
    model: str,
    temperature: float,
    json_mode: bool,
    max_tokens: int,
) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.api_key)
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(Exception),
    before_sleep=lambda retry_state: logger.warning(
        "Anthropic call failed (attempt %d), retrying: %s",
        retry_state.attempt_number,
        retry_state.outcome.exception(),
    ),
    reraise=True,
)
async def _anthropic_chat(
    messages: list[dict],
    model: str,
    temperature: float,
    json_mode: bool,
    max_tokens: int,
) -> str:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Anthropic uses a separate system parameter, not a system message
    system_text = ""
    chat_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_text += msg["content"] + "\n"
        else:
            chat_messages.append({"role": msg["role"], "content": msg["content"]})

    if json_mode:
        system_text += "\nYou MUST respond with valid JSON only. No other text.\n"

    kwargs: dict = {
        "model": model,
        "messages": chat_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if system_text.strip():
        kwargs["system"] = system_text.strip()

    response = await client.messages.create(**kwargs)
    return response.content[0].text
