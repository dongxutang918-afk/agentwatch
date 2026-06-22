"""Risk policy evaluation — danger detection, drift detection, failure counting."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentwatch.store import increment_failure_count, reset_failure_count, load_state


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
    npolicy.setdefault("notify_on_session_summary", True)
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

    # Session summary (rich end-of-session digest) — mode-independent, on by
    # default.  Clean Stop is only classified as session_summary when this is
    # enabled, but we re-check here so the routing is explicit.
    if event_type == "session_summary":
        return npolicy.get("notify_on_session_summary", True)

    if mode == "verbose":
        return True

    # actionable mode — only push truly interactive events.
    if event_type == "task_done" and npolicy.get("notify_on_task_done", True):
        return True
    if event_type in ("permission_required", "attention_required") and npolicy.get("notify_on_interactive_attention", True):
        return True

    # danger / drift / failure are silent in actionable mode.
    return False
