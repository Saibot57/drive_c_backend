"""Lightweight client for calling external language models."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

import requests
from requests import RequestException
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class LLMError(Exception):
    """Raised when the LLM returns an unexpected or invalid response."""


PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
MODEL = os.getenv("LLM_MODEL", "claude-3-5-sonnet-20240620")
API_KEY = os.getenv("LLM_API_KEY", "")
TIMEOUT = int(os.getenv("LLM_HTTP_TIMEOUT_SECONDS", "25"))
MAX_TOKENS = int(os.getenv("AI_PARSE_MAX_TOKENS", "1024"))


def _anthropic_endpoint() -> str:
    return "https://api.anthropic.com/v1/messages"


def _anthropic_headers() -> Dict[str, str]:
    return {
        "content-type": "application/json",
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
    }


def _extract_first_json_blob(text: str) -> str:
    """Extract the first JSON object/array found in ``text``."""

    if not text:
        raise LLMError("No content returned from LLM response")

    block = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.S)
    if block:
        return block.group(1)

    brace = re.search(r"(\{.*\})", text, re.S)
    bracket = re.search(r"(\[.*\])", text, re.S)
    candidate = (brace.group(1) if brace else None) or (bracket.group(1) if bracket else None)
    if not candidate:
        raise LLMError("No JSON found in LLM response")
    return candidate


def _extract_text_from_response(payload: Dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, list) and content:
        segment = content[0]
        if isinstance(segment, dict):
            return str(segment.get("text", ""))
    return ""


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.8, min=1, max=6),
    retry=retry_if_exception_type((RequestException, LLMError)),
)
def parse_schedule_with_llm(prompt: str) -> List[Dict[str, Any]]:
    """Send ``prompt`` to the configured LLM provider and parse the JSON array."""

    if PROVIDER != "anthropic":
        raise LLMError(f"Unsupported provider: {PROVIDER}")
    if not API_KEY:
        raise LLMError("LLM_API_KEY is not configured")

    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }

    response = requests.post(
        _anthropic_endpoint(),
        headers=_anthropic_headers(),
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    text = _extract_text_from_response(data)
    json_blob = _extract_first_json_blob(text)

    try:
        activities = json.loads(json_blob)
    except json.JSONDecodeError as exc:
        raise LLMError("Failed to decode JSON from LLM response") from exc

    if not isinstance(activities, list):
        raise LLMError("Expected a JSON array of activities")

    return activities
