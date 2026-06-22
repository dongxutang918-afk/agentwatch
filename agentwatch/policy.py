"""Risk policy evaluation — danger detection, drift detection, failure counting."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentwatch.store import increment_failure_count, reset_failure_count, load_state, get_away


# Pre-compiled regex patterns for destructive keywords with word-boundary matching.
_DESTRUCTIVE_KW_PATTERNS = [
    re.compile(rf"\b{re.escape(kw)}\b") for kw in ("rm", "delete", "sudo", "chmod", "chown", "push", "reset")
]


def evaluate_danger(tool_name: str, raw_text: str, risk_policy: dict[str, Any]) -> dict[str, Any] | None:
    """Check whether *raw_text* matches any dangerous patterns.

    Returns a dict with {risk, matched_keywords, suggestion} or None.
    """
    dangerous_commands = risk_policy.get("dangerous_commands", [])
    dangerous_paths = risk_policy.get("dangerous_paths", [])
    protected_paths = risk_policy.get("protected_paths", [])
    dangerous_extensions = risk_policy.get("dangerous_file_extensions", [])

    # Additional deletion-related commands that are always suspicious in an agent context.
    deletion_markers = [
        "rm ", "rm -rf", "unlink", "delete", "trash", "shred",
        "git reset --hard", "git clean", "git push --force", "git push -f",
        "DROP TABLE", "DELETE FROM", "TRUNCATE",
    ]

    text_lower = raw_text.lower()
    matched: list[str] = []

    for cmd in dangerous_commands:
        if cmd.lower() in text_lower:
            matched.append(cmd)

    for path in dangerous_paths:
        if path.lower() in text_lower:
            matched.append(path)

    for ext in dangerous_extensions:
        if ext.lower() in text_lower:
            matched.append(ext)

    for protected in protected_paths:
        if protected.lower() in text_lower:
            matched.append(protected)

    for dm in deletion_markers:
        if dm.lower() in text_lower:
            if dm not in matched:
                matched.append(dm)

    # Also check tool_name for write/destructive tools.
    destructive_tools = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"}
    if tool_name in destructive_tools:
        # Mark as potentially dangerous, but only if we also see destructive keywords
        # (using word-boundary matching to avoid false positives like "rm" in "permissions").
        if any(p.search(text_lower) for p in _DESTRUCTIVE_KW_PATTERNS):
            if "destructive_tool" not in matched:
                matched.append(f"destructive_tool:{tool_name}")

    if not matched:
        return None

    # Determine risk level.
    critical_keywords = {"rm -rf", "sudo rm", "dd ", "mkfs", "git reset --hard", "git push --force",
                         "DROP TABLE", "DELETE FROM", "TRUNCATE"}
    high_keywords = {"sudo", "git push", "git clean", "chmod", "chown", "killall",
                     ".env", ".ssh", "id_rsa", "id_ed25519", "token", "credentials", "private_key",
                     "secrets", ".pem", ".key"}

    risk = "中"
    for m in matched:
        if any(c in m.lower() for c in critical_keywords):
            risk = "极高"
            break
        if any(h in m.lower() for h in high_keywords):
            risk = "高"

    suggestion = "立即回电脑确认" if risk in ("高", "极高") else "建议回电脑检查"

    return {
        "risk": risk,
        "matched_keywords": matched,
        "suggestion": suggestion,
    }


def evaluate_drift(raw_text: str, task_boundary: dict[str, Any]) -> dict[str, Any] | None:
    """Check whether the action wanders outside the declared task boundary.

    Returns a dict or None.
    """
    if not task_boundary.get("enabled", False):
        return None

    task_name = task_boundary.get("task_name", "未命名任务")
    forbidden_paths = task_boundary.get("forbidden_paths", [])
    forbidden_keywords = task_boundary.get("forbidden_keywords", [])

    text_lower = raw_text.lower()
    matched: list[str] = []

    for fp in forbidden_paths:
        if fp.lower() in text_lower:
            matched.append(fp)

    for kw in forbidden_keywords:
        if kw.lower() in text_lower:
            matched.append(kw)

    if not matched:
        return None

    return {
        "risk": "中",
        "task_name": task_name,
        "matched_boundary_violations": matched,
        "suggestion": "收窄任务或回电脑查看",
    }


def evaluate_failure(parsed: dict[str, Any], failure_policy: dict[str, Any]) -> dict[str, Any] | None:
    """Check consecutive failure count and decide whether to alert.

    Returns a dict or None.
    """
    if not parsed.get("has_error"):
        reset_failure_count()
        return None

    threshold = failure_policy.get("consecutive_failure_threshold", 3)
    count = increment_failure_count()

    if count < threshold:
        return None

    return {
        "risk": "中",
        "consecutive_failures": count,
        "suggestion": f"连续失败 {count} 次，可能卡住，请回电脑查看",
    }


# ── Notification routing ─────────────────────────────────────────────────


def get_notification_policy(config: dict[str, Any]) -> dict[str, Any]:
    """Return the notification_policy dict, with sensible defaults."""
    npolicy = config.get("notification_policy", {}) or {}
    npolicy.setdefault("mode", "actionable")
    npolicy.setdefault("notify_on_task_done", True)
    npolicy.setdefault("notify_on_interactive_attention", True)
    npolicy.setdefault("notify_on_pretooluse", False)
    npolicy.setdefault("notify_on_danger", False)
    npolicy.setdefault("notify_on_drift", False)
    npolicy.setdefault("notify_on_failure", False)
    npolicy.setdefault("log_silent_events", True)
    return npolicy


def should_send_notification(event_type: str, npolicy: dict[str, Any]) -> bool:
    """Decide whether an event of *event_type* should push to Apple Watch.

    In 'actionable' mode (default):
      - task_done, permission_required, attention_required → push
      - danger, drift, failure, info → silent (log only)

    In 'verbose' mode:
      - All non-info types → push (legacy behavior)
    """
    mode = npolicy.get("mode", "actionable")

    # Always-silent types (possible_permission_wait is log-only by default).
    if event_type in ("info", "pretooluse", "posttooluse", "posttooluse_error",
                       "possible_permission_wait", "permission_denied"):
        return False

    if mode == "verbose":
        return True

    # actionable mode — only push truly interactive events.
    if event_type == "task_done" and npolicy.get("notify_on_task_done", True):
        return True
    if event_type in ("permission_required", "attention_required") and npolicy.get("notify_on_interactive_attention", True):
        return True

    # danger / drift / failure are silent in actionable mode.
    return False


# ── Away mode ────────────────────────────────────────────────────────────

# Event types that stay pushable even while Away mode is active — a failing
# agent or anything needing user interaction. Extend per-config via
# away_mode.extra_critical_events.
CRITICAL_EVENT_TYPES: frozenset[str] = frozenset({
    "failure",
    "permission_required",
    "attention_required",
})


def get_away_mode(config: dict[str, Any]) -> dict[str, Any]:
    """Return the away_mode config block with defaults applied."""
    am = config.get("away_mode", {}) or {}
    am.setdefault("enabled", True)
    am.setdefault("extra_critical_events", [])
    am.setdefault("schedule", {})
    return am


def is_event_critical(event_type: str, config: dict[str, Any]) -> bool:
    """True if *event_type* should bypass Away-mode suppression."""
    if event_type in CRITICAL_EVENT_TYPES:
        return True
    return event_type in set(get_away_mode(config).get("extra_critical_events", []))


def _parse_window(spec: str) -> tuple[int, int] | None:
    """Parse a "HH:MM-HH:MM" window into (start_minute, end_minute), or None.

    Returns None on any malformed input so a bad config line is silently
    skipped rather than throwing inside a hook.
    """
    try:
        start_s, end_s = spec.split("-", 1)
        sh, sm = (int(x) for x in start_s.strip().split(":", 1))
        eh, em = (int(x) for x in end_s.strip().split(":", 1))
    except (ValueError, AttributeError):
        return None
    if not (0 <= sh < 24 and 0 <= sm < 60 and 0 <= eh < 24 and 0 <= em < 60):
        return None
    return sh * 60 + sm, eh * 60 + em


def in_dnd_window(now_minute: int, windows: list[str]) -> bool:
    """True if *now_minute* (minutes since local midnight) falls in any window.

    A window whose start > end (e.g. 23:00-08:00) wraps past midnight.  A
    zero-length window (start == end) matches nothing.  Malformed specs are
    skipped.
    """
    for spec in windows or []:
        parsed = _parse_window(spec)
        if parsed is None:
            continue
        start, end = parsed
        if start == end:
            continue
        if start < end:
            if start <= now_minute < end:
                return True
        elif now_minute >= start or now_minute < end:  # wraps midnight
            return True
    return False


def schedule_active(config: dict[str, Any], now: Any = None) -> bool:
    """True when the away schedule is enabled and *now* is inside a DND window.

    *now* is a datetime (defaults to the local current time); only its hour and
    minute are read.  Returns False when the schedule sub-block is disabled, so
    the schedule layer is opt-in and leaves pure-manual setups untouched.
    """
    sched = get_away_mode(config).get("schedule") or {}
    if not sched.get("enabled"):
        return False
    if now is None:
        from datetime import datetime
        now = datetime.now()
    return in_dnd_window(now.hour * 60 + now.minute, sched.get("windows", []))


def away_suppresses(event_type: str, config: dict[str, Any]) -> bool:
    """True when Away mode is active and *event_type* is not critical.

    Away is active when manually toggled on (``get_away().active``) OR when the
    optional schedule places *now* inside a DND window — the two compose as a
    plain OR, so a manual ``away off`` does not lift a scheduled window.

    Layered ON TOP of should_send_notification: it only ever turns a would-be
    push into silence, never the reverse. Critical events are never suppressed.
    """
    if not get_away_mode(config).get("enabled", True):
        return False
    if not (get_away().get("active") or schedule_active(config)):
        return False
    return not is_event_critical(event_type, config)
