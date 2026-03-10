"""REST endpoints for multi-turn AI chat sessions."""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from flask import Blueprint, jsonify, request
from requests import RequestException
from requests.exceptions import Timeout

from api.auth_routes import token_required
from models.schedule_models import FamilyMember
from services.ai_postprocess import normalize_and_align
from services.chat_llm import chat_with_llm
from services.chat_prompts import build_chat_system_prompt
from services.chat_session import (
    add_message,
    create_session,
    delete_session,
    get_messages,
    get_system_prompt,
)
from services.llm_client import LLMError

logger = logging.getLogger(__name__)

chat_api = Blueprint("chat_api", __name__)

_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


# --- Helpers ---

def _success(data=None, status_code=200):
    return jsonify({"success": True, "data": data or {}, "error": None}), status_code


def _error(message, status_code=400):
    return jsonify({"success": False, "data": None, "error": message}), status_code


def _extract_json_from_response(text: str):
    """Extract a JSON array from a ```json code fence, or None."""
    match = _JSON_FENCE_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


def _ensure_series_id(activity: dict) -> dict:
    import uuid as _uuid
    normalized = dict(activity)
    sid = normalized.get("seriesId")
    if not (isinstance(sid, str) and _UUID_RE.match(sid)):
        normalized["seriesId"] = str(_uuid.uuid4())
    return normalized


def _postprocess_activities(raw_activities, fm_context, week, year):
    """Normalize, validate and return activities, or raise on failure."""
    aligned = normalize_and_align(raw_activities, fm_context, week, year)
    aligned = [_ensure_series_id(a) for a in aligned]

    # Import validate helper from schedule_routes (avoid circular by late import)
    from api.schedule_routes import _validate_activity_payload

    validated = []
    for activity in aligned:
        try:
            v = _validate_activity_payload(activity)
            sanitized = dict(v)
            recurring_end = sanitized.get("recurringEndDate")
            if isinstance(recurring_end, date):
                sanitized["recurringEndDate"] = recurring_end.isoformat()
            validated.append(sanitized)
        except ValueError as exc:
            logger.warning("Dropping invalid chat activity: %s", exc)
            continue

    return validated


# --- Endpoints ---

@chat_api.route("/sessions", methods=["POST"])
@token_required
def create_chat_session(current_user):
    """Create a new chat session with the schedule assistant."""
    data = request.get_json(silent=True) or {}
    week = data.get("week")
    year = data.get("year")

    members = (
        FamilyMember.query.filter_by(user_id=current_user.id)
        .order_by(FamilyMember.name.asc())
        .all()
    )
    fm_context = [{"id": m.id, "name": m.name} for m in members]

    system_prompt = build_chat_system_prompt(fm_context, week, year)
    session_id = create_session(str(current_user.id), system_prompt)

    return _success({"sessionId": session_id}), 201


@chat_api.route("/sessions/<session_id>/messages", methods=["POST"])
@token_required
def send_chat_message(current_user, session_id):
    """Send a user message and get the assistant reply."""
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()

    if not user_message:
        return _error("Meddelande saknas.", 400)
    if len(user_message) > 2000:
        return _error("Meddelandet är för långt (max 2000 tecken).", 400)

    user_id = str(current_user.id)

    try:
        system_prompt = get_system_prompt(session_id, user_id)
    except KeyError:
        return _error("Session hittades inte.", 404)

    try:
        add_message(session_id, user_id, "user", user_message)
    except ValueError as exc:
        return _error(str(exc), 400)

    messages = get_messages(session_id, user_id)

    try:
        assistant_text = chat_with_llm(system_prompt, messages)
    except LLMError as exc:
        logger.warning("Chat LLM error for user %s: %s", user_id, exc)
        return _error(str(exc), 503)
    except Timeout:
        return _error("AI-tjänsten tog för lång tid att svara.", 502)
    except RequestException as exc:
        logger.warning("Chat LLM request error for user %s: %s", user_id, exc)
        return _error("Kunde inte kontakta AI-tjänsten.", 502)

    add_message(session_id, user_id, "assistant", assistant_text)

    # Check if the response contains final JSON
    raw_activities = _extract_json_from_response(assistant_text)
    result = {
        "message": assistant_text,
        "activities": None,
        "isComplete": False,
    }

    if raw_activities is not None:
        # Get family members for post-processing
        members = (
            FamilyMember.query.filter_by(user_id=current_user.id)
            .order_by(FamilyMember.name.asc())
            .all()
        )
        fm_context = [{"id": m.id, "name": m.name} for m in members]

        # Extract week/year from session creation context
        # (best effort: use first activity's week/year or None)
        week = raw_activities[0].get("week") if raw_activities else None
        year = raw_activities[0].get("year") if raw_activities else None

        try:
            validated = _postprocess_activities(raw_activities, fm_context, week, year)
            if validated:
                result["activities"] = validated
                result["isComplete"] = True
            else:
                result["error"] = "JSON hittades men inga giltiga aktiviteter efter validering."
        except ValueError as exc:
            result["error"] = str(exc)

    return _success(result)


@chat_api.route("/sessions/<session_id>", methods=["DELETE"])
@token_required
def delete_chat_session(current_user, session_id):
    """Delete a chat session."""
    delete_session(session_id, str(current_user.id))
    return "", 204
