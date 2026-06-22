"""JSONL event store and state persistence for AgentWatch."""

import json
import re
import uuid
from pathlib import Path
from typing import Any

from agentwatch.config import LOGS_DIR, STATE_FILE, CONFIG_FILE

EVENTS_LOG = LOGS_DIR / "agentwatch_events.jsonl"
PENDING_ACTIONS_FILE = LOGS_DIR / "pending_actions.json"

# Lazy-loaded bark_key for log sanitisation.
_SANITISE_PATTERNS: list[tuple[re.Pattern[str], str]] | None = None


def _ensure_logs_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _get_sanitisers() -> list[tuple[re.Pattern[str], str]]:
    """Build regex patterns to redact sensitive values from log entries."""
    global _SANITISE_PATTERNS
    if _SANITISE_PATTERNS is not None:
        return _SANITISE_PATTERNS
    _SANITISE_PATTERNS = []
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                config = json.load(fh)
            bark_key = config.get("notifier", {}).get("bark_key", "")
            if bark_key and bark_key != "YOUR_BARK_KEY" and len(bark_key) > 8:
                _SANITISE_PATTERNS.append(
                    (re.compile(re.escape(bark_key)), f"{bark_key[:4]}{'*' * (len(bark_key) - 8)}{bark_key[-4:]}")
                )
    except Exception:
        pass
    return _SANITISE_PATTERNS


def _redact(text: str) -> str:
    """Replace any sensitive values in *text* with redacted versions."""
    for pattern, replacement in _get_sanitisers():
        text = pattern.sub(replacement, text)
    return text


def append_event(event: dict[str, Any]) -> None:
    """Append a single event dict as one JSON line to the events log.

    Bark key (and other secrets) are automatically redacted from the raw_event
    before writing, so they never appear in plaintext on disk.
    """
    _ensure_logs_dir()
    safe = dict(event)
    # Redact raw_event by serialising → redacting → deserialising.
    if "raw_event" in safe and isinstance(safe["raw_event"], dict):
        try:
            serialised = json.dumps(safe["raw_event"], ensure_ascii=False)
            redacted = _redact(serialised)
            safe["raw_event"] = json.loads(redacted)
        except Exception:
            pass  # If redaction fails, write the original — better than crashing.
    with open(EVENTS_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(safe, ensure_ascii=False) + "\n")


def load_state() -> dict[str, Any]:
    """Load persisted state from state.json (task boundaries, failure count, etc.)."""
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    """Persist state dict to state.json."""
    _ensure_logs_dir()
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def increment_failure_count() -> int:
    """Increment consecutive failure counter; return the new count."""
    state = load_state()
    count = state.get("consecutive_failures", 0) + 1
    state["consecutive_failures"] = count
    save_state(state)
    return count


def reset_failure_count() -> None:
    """Reset consecutive failure counter to 0."""
    state = load_state()
    state["consecutive_failures"] = 0
    save_state(state)


def set_away(active: bool) -> dict[str, Any]:
    """Toggle Away mode on/off in persisted state; return the new away record."""
    state = load_state()
    away = {"active": bool(active), "since": timestamp_default()}
    state["away"] = away
    save_state(state)
    return away


def get_away() -> dict[str, Any]:
    """Return the persisted away record ({} when never set)."""
    return load_state().get("away", {}) or {}


def tail_logs(n: int = 20) -> list[dict[str, Any]]:
    """Return the last *n* events from the JSONL log."""
    if not EVENTS_LOG.exists():
        return []
    lines: list[str] = []
    with open(EVENTS_LOG, "r", encoding="utf-8") as fh:
        for line in fh:
            lines.append(line.strip())
            if len(lines) > n:
                lines.pop(0)
    events: list[dict[str, Any]] = []
    for line in lines[-n:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"raw": line, "parse_error": True})
    return events


# ── Pending actions (approval detection) ──────────────────────────────────


def _load_pending_actions() -> list[dict[str, Any]]:
    """Load the pending-actions array from disk."""
    _ensure_logs_dir()
    if not PENDING_ACTIONS_FILE.exists():
        return []
    try:
        with open(PENDING_ACTIONS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, list):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_pending_actions(actions: list[dict[str, Any]]) -> None:
    """Atomically write the pending-actions array to disk."""
    _ensure_logs_dir()
    tmp = PENDING_ACTIONS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(actions, fh, ensure_ascii=False, indent=2)
    tmp.replace(PENDING_ACTIONS_FILE)


def add_pending_action(
    action_id: str,
    tool_name: str,
    summary: str,
    tool_use_id: str = "",
) -> dict[str, Any]:
    """Register a new pending approval candidate.

    Returns the newly-created action dict.
    """
    actions = _load_pending_actions()
    now = timestamp_default()
    entry: dict[str, Any] = {
        "id": action_id,
        "created_at": now,
        "event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "summary": summary[:160] if len(summary) > 160 else summary,
        "status": "pending",
        "notified": False,
        "cleared_at": None,
    }
    actions.append(entry)
    _save_pending_actions(actions)
    return entry


def clear_pending_action_by_match(tool_use_id: str = "", tool_name: str = "") -> str | None:
    """Mark a pending action as cleared by PostToolUse.

    Matching priority:
    1. Exact tool_use_id match.
    2. tool_name match on the most recent pending entry.

    Returns the cleared action_id or None.
    """
    actions = _load_pending_actions()
    if not actions:
        return None

    cleared: str | None = None
    now = timestamp_default()

    # Try exact tool_use_id match first.
    if tool_use_id:
        for a in actions:
            if a.get("status") == "pending" and a.get("tool_use_id") == tool_use_id:
                a["status"] = "cleared"
                a["cleared_at"] = now
                cleared = a["id"]
                break

    # Fallback: most recent pending with matching tool_name.
    if not cleared and tool_name:
        for a in reversed(actions):
            if a.get("status") == "pending" and a.get("tool_name") == tool_name:
                a["status"] = "cleared"
                a["cleared_at"] = now
                cleared = a["id"]
                break

    if cleared:
        _save_pending_actions(actions)

    return cleared


def get_pending_action(action_id: str) -> dict[str, Any] | None:
    """Return a specific pending action by id, or None."""
    actions = _load_pending_actions()
    for a in actions:
        if a.get("id") == action_id:
            return a
    return None


def mark_pending_notified(action_id: str) -> bool:
    """Mark a pending action as notified. Returns True if updated."""
    actions = _load_pending_actions()
    for a in actions:
        if a.get("id") == action_id and a.get("status") == "pending":
            a["notified"] = True
            _save_pending_actions(actions)
            return True
    return False


def count_pending() -> int:
    """Return the number of currently-pending (uncleared) actions."""
    actions = _load_pending_actions()
    return sum(1 for a in actions if a.get("status") == "pending")


def new_action_id() -> str:
    """Generate a unique pending-action id."""
    return uuid.uuid4().hex[:16]


def timestamp_default() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
