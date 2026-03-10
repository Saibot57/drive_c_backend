"""In-memory chat session manager for multi-turn AI conversations."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
_sessions: Dict[str, Dict[str, Any]] = {}

SESSION_TTL_MINUTES = 30
MAX_MESSAGES = 50


def _purge_expired() -> None:
    """Remove sessions older than TTL. Must be called under _lock."""
    cutoff = datetime.utcnow() - timedelta(minutes=SESSION_TTL_MINUTES)
    expired = [sid for sid, s in _sessions.items() if s["last_active"] < cutoff]
    for sid in expired:
        del _sessions[sid]


def create_session(user_id: str, system_prompt: str) -> str:
    """Create a new chat session. Returns session_id."""
    session_id = str(uuid.uuid4())
    now = datetime.utcnow()
    with _lock:
        _purge_expired()
        _sessions[session_id] = {
            "user_id": user_id,
            "system_prompt": system_prompt,
            "messages": [],
            "created_at": now,
            "last_active": now,
        }
    return session_id


def add_message(session_id: str, user_id: str, role: str, content: str) -> None:
    """Append a message to the session history."""
    with _lock:
        session = _sessions.get(session_id)
        if not session or session["user_id"] != user_id:
            raise KeyError("Session not found")
        if len(session["messages"]) >= MAX_MESSAGES:
            raise ValueError("Session message limit reached")
        session["messages"].append({"role": role, "content": content})
        session["last_active"] = datetime.utcnow()


def get_messages(session_id: str, user_id: str) -> List[Dict[str, str]]:
    """Return the message history for a session."""
    with _lock:
        session = _sessions.get(session_id)
        if not session or session["user_id"] != user_id:
            raise KeyError("Session not found")
        return list(session["messages"])


def get_system_prompt(session_id: str, user_id: str) -> str:
    """Return the system prompt for a session."""
    with _lock:
        session = _sessions.get(session_id)
        if not session or session["user_id"] != user_id:
            raise KeyError("Session not found")
        return session["system_prompt"]


def delete_session(session_id: str, user_id: str) -> None:
    """Delete a session."""
    with _lock:
        session = _sessions.get(session_id)
        if session and session["user_id"] == user_id:
            del _sessions[session_id]
