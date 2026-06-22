"""Aggregate one Claude Code session's logged events into a human-readable summary.

Pure functions only — no disk / config / network access.  The caller supplies
the already-loaded event dicts (as written by :func:`agentwatch.store.append_event`)
so the aggregation can be unit-tested without touching the filesystem.

A "session" is identified by the ``session_id`` field that Claude Code injects
into every real hook payload (stored under each event's ``raw_event``).
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime
from typing import Any

# Tools that mutate files — their tool_input carries a file_path we want to list.
_FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _raw(event: dict[str, Any]) -> dict[str, Any]:
    """Return an event's raw_event payload, or an empty dict."""
    re = event.get("raw_event")
    return re if isinstance(re, dict) else {}


def events_for_session(events: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]]:
    """Filter *events* down to those belonging to *session_id*.

    Events without a matching ``raw_event.session_id`` (e.g. simulate /
    pending_check entries) are excluded.
    """
    if not session_id:
        return []
    return [e for e in events if _raw(e).get("session_id") == session_id]


def _parse_ts(ts: str) -> datetime | None:
    """Parse an ISO timestamp string, tolerating a trailing 'Z'."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def summarize_session(events: list[dict[str, Any]], session_id: str) -> dict[str, Any]:
    """Aggregate one session's events into a structured summary.

    Counts tool *completions* (PostToolUse) so each real tool call is counted
    once.  Returns a dict with: tool_calls, tools (name→count), files (list of
    basenames), commands (list), failures, dangers, drifts, duration_seconds.
    """
    rows = events_for_session(events, session_id)

    tools: Counter[str] = Counter()
    files: list[str] = []
    seen_files: set[str] = set()
    commands: list[str] = []
    failures = 0
    dangers = 0
    drifts = 0

    for e in rows:
        raw = _raw(e)
        event_name = e.get("event_name", "")
        event_type = e.get("event_type", "")
        tool_name = raw.get("tool_name", "")
        tool_input = raw.get("tool_input") or {}

        if event_type == "danger":
            dangers += 1
        elif event_type == "drift":
            drifts += 1
        if event_type in ("posttooluse_error", "failure"):
            failures += 1

        # Count a tool as "run" on its PostToolUse (fires once per completion).
        if event_name == "PostToolUse" and tool_name:
            tools[tool_name] += 1
            if tool_name in _FILE_TOOLS and isinstance(tool_input, dict):
                fp = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
                if fp:
                    base = os.path.basename(str(fp)) or str(fp)
                    if base not in seen_files:
                        seen_files.add(base)
                        files.append(base)
            elif tool_name == "Bash" and isinstance(tool_input, dict):
                cmd = str(tool_input.get("command", "")).strip()
                if cmd:
                    commands.append(cmd)

    # Duration: first → last event timestamp within the session.
    times = [t for t in (_parse_ts(e.get("timestamp", "")) for e in rows) if t]
    duration_seconds = 0
    if len(times) >= 2:
        duration_seconds = int((max(times) - min(times)).total_seconds())

    return {
        "session_id": session_id,
        "tool_calls": sum(tools.values()),
        "tools": dict(tools),
        "files": files,
        "commands": commands,
        "failures": failures,
        "dangers": dangers,
        "drifts": drifts,
        "duration_seconds": duration_seconds,
    }


def _fmt_duration(seconds: int) -> str:
    """Render a duration in compact Chinese (e.g. '8 分钟', '2 小时 5 分钟')."""
    if seconds < 60:
        return f"{seconds} 秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, mins = divmod(minutes, 60)
    return f"{hours} 小时 {mins} 分钟" if mins else f"{hours} 小时"


def render_summary_body(summary: dict[str, Any], max_files: int = 4) -> str:
    """Build a Watch-friendly body string from a :func:`summarize_session` dict."""
    calls = summary.get("tool_calls", 0)
    files = summary.get("files", [])
    commands = summary.get("commands", [])
    failures = summary.get("failures", 0)
    duration = summary.get("duration_seconds", 0)

    # Headline metrics line.
    parts = [f"工具调用 {calls} 次"]
    if files:
        parts.append(f"改动文件 {len(files)} 个")
    if commands:
        parts.append(f"命令 {len(commands)} 条")
    if failures:
        parts.append(f"失败 {failures} 次")
    lines = [" · ".join(parts)]

    if files:
        shown = files[:max_files]
        more = f" 等 {len(files)} 个" if len(files) > max_files else ""
        lines.append("改动：" + ", ".join(shown) + more)

    if duration > 0:
        lines.append("耗时 " + _fmt_duration(duration))

    risk = "中" if failures else "低"
    lines.append(f"风险：{risk}")
    lines.append("建议：回电脑验收或给下一步指示")
    return "\n".join(lines)
