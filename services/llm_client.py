"""Lightweight client for calling external language models."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

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


def _match_balanced_json(text: str, start: int) -> Tuple[str, int]:
    """Return the JSON blob that starts at ``start`` and its end index."""

    opening = text[start]
    pairs = {"[": "]", "{": "}"}
    if opening not in pairs:
        raise LLMError("Invalid JSON start character")

    expected: List[str] = [pairs[opening]]
    i = start + 1
    in_string = False
    escape = False

    while i < len(text):
        char = text[i]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char in pairs:
                expected.append(pairs[char])
            elif char in (']', '}'):
                if not expected or char != expected[-1]:
                    raise LLMError("Mismatched JSON braces in LLM response")
                expected.pop()
                if not expected:
                    return text[start : i + 1], i

        i += 1

    raise LLMError("Unterminated JSON blob in LLM response")


def _extract_first_json_blob(text: str) -> str:
    """Extract the first complete JSON object/array found in ``text``."""

    if not text:
        raise LLMError("No content returned from LLM response")

    candidates: List[Tuple[int, str, str]] = []
    i = 0
    length = len(text)

    while i < length:
        char = text[i]
        if char in ('[', '{'):
            try:
                blob, end = _match_balanced_json(text, i)
            except LLMError:
                i += 1
                continue
            candidates.append((i, char, blob))
            i = end
        i += 1

    if not candidates:
        raise LLMError("No JSON found in LLM response")

    array_candidates = [item for item in candidates if item[1] == '[']
    if array_candidates:
        array_candidates.sort(key=lambda item: item[0])
        return array_candidates[0][2]

    candidates.sort(key=lambda item: item[0])
    return candidates[0][2]


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
