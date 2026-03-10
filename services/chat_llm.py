"""Multi-turn LLM chat client.

Sends a system prompt + message history to the configured LLM provider
and returns the raw assistant text (which may or may not contain JSON).
"""
from __future__ import annotations

from typing import Any, Dict, List

import requests
from requests import RequestException
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from services.llm_client import (
    TIMEOUT,
    MAX_TOKENS,
    LLMError,
    _get_llm_config,
    _anthropic_endpoint,
    _anthropic_headers,
    _gemini_endpoint,
    _gemini_headers,
    _extract_text_from_anthropic_response,
    _extract_text_from_gemini_response,
)


def _build_anthropic_payload(
    model: str,
    system_prompt: str,
    messages: List[Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
    }


def _build_gemini_payload(
    system_prompt: str,
    messages: List[Dict[str, str]],
) -> Dict[str, Any]:
    # Gemini uses "user" / "model" roles
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    return {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": MAX_TOKENS,
        },
    }


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.8, min=1, max=6),
    retry=retry_if_exception_type((RequestException, LLMError)),
)
def chat_with_llm(
    system_prompt: str,
    messages: List[Dict[str, str]],
) -> str:
    """Send a multi-turn conversation to the LLM and return the assistant text."""

    if not messages:
        raise LLMError("No messages provided")

    provider, api_key, model = _get_llm_config()

    if provider == "anthropic":
        payload = _build_anthropic_payload(model, system_prompt, messages)
        response = requests.post(
            _anthropic_endpoint(),
            headers=_anthropic_headers(api_key),
            json=payload,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return _extract_text_from_anthropic_response(response.json())

    elif provider == "gemini":
        payload = _build_gemini_payload(system_prompt, messages)
        response = requests.post(
            _gemini_endpoint(model, api_key),
            headers=_gemini_headers(),
            json=payload,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return _extract_text_from_gemini_response(response.json())

    else:
        raise LLMError(f"Unsupported provider: {provider}")
