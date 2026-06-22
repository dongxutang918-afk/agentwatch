#!/usr/bin/env python3
"""AgentWatch CLI — the main entry point invoked by `agentwatch` or `python -m agentwatch.cli`."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentwatch.config import (
    CONFIG_FILE,
    EXAMPLE_CONFIG_FILE,
    LOGS_DIR,
    STATE_FILE,
    init_config,
    load_config,
    get_notifier_config,
    get_risk_policy,
    get_task_boundary,
    get_failure_policy,
)
from agentwatch.event_parser import (
    parse_event,
    extract_tool_identity,
    extract_tool_summary,
    make_pending_action_id,
)
from agentwatch.classifier import classify, classify_simulated
from agentwatch.policy import (
    evaluate_danger,
    evaluate_drift,
    evaluate_failure,
    get_notification_policy,
    should_send_notification,
)
from agentwatch.message_builder import build_message
from agentwatch.notifier import send_bark
from agentwatch.store import (
    append_event,
    load_state,
    save_state,
    tail_logs,
    EVENTS_LOG,
    add_pending_action,
    clear_pending_action_by_match,
    get_pending_action,
    mark_pending_notified,
    count_pending,
)
from agentwatch.utils import read_stdin_json, timestamp_iso, mask_key, parse_bark_input


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _ansi(code: str) -> str:
    """Return an ANSI escape sequence."""
    codes: dict[str, str] = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "clear": "\033[2J\033[H",
    }
    return codes.get(code, "")


def _risk_color(risk: str) -> str:
    mapping = {"极高": _ansi("red"), "高": _ansi("red"), "中": _ansi("yellow"), "低": _ansi("green")}
    return mapping.get(risk, _ansi("reset"))


# ---------------------------------------------------------------------------
# subcommands — existing
# ---------------------------------------------------------------------------


def cmd_init() -> None:
    """Create config.json and logs/ directory."""
    init_config()
    print(f"[AgentWatch] Logs directory: {LOGS_DIR}")
    print("[AgentWatch] Init complete. Next steps:")
    print("  1. Edit config.json → set notifier.bark_key")
    print("  2. Run 'agentwatch test-push' to verify notifications")
    print("  3. Run 'bash install_claude_hooks.sh' to wire up Claude Code hooks")


def cmd_test_push() -> None:
    """Send a test Bark notification."""
    config = load_config()
    nc = get_notifier_config(config)
    key = nc.get("bark_key", "")
    print(f"[AgentWatch] Using bark_key: {mask_key(key)}")
    print("[AgentWatch] Sending test notification ...")

    ok = send_bark("AgentWatch 测试", "如果你在 Apple Watch 上看到这条消息，说明提醒链路已打通。", nc)
    if ok:
        print("[AgentWatch] Test notification sent. Check your iPhone / Apple Watch.")
    else:
        print("[AgentWatch] Failed to send notification. Check your bark_key and network.")
        raise SystemExit(1)


def cmd_hook(event_name: str) -> None:
    """Claude Code hook entry point.

    Reads JSON from stdin, parses / classifies / evaluates policy,
    builds a Watch message, pushes via Bark, and logs the event.
    NEVER exits non-zero — a hook crash must not block Claude Code.

    PreToolUse: registers approval candidates and spawns delayed checker.
    PostToolUse: clears matching pending actions.
    """
    try:
        raw = read_stdin_json()
        parsed = parse_event(raw, event_name)
        category = classify(parsed)

        config = load_config()
        risk_policy = get_risk_policy(config)
        task_boundary = get_task_boundary(config)
        failure_policy = get_failure_policy(config)
        npolicy = get_notification_policy(config)
        nc = get_notifier_config(config)
        notification_mode = npolicy.get("mode", "actionable")

        # Approval detection config.
        approval_cfg = config.get("approval_detection", {}) or {}
        approval_enabled = approval_cfg.get("enabled", True) and notification_mode == "actionable"
        candidate_tools = set(approval_cfg.get("candidate_tools", ["Bash", "Edit", "Write", "MultiEdit", "NotebookEdit"]))
        delay_seconds = approval_cfg.get("delay_seconds", 4)

        # Merge active task boundary from state.
        state = load_state()
        active_task = state.get("active_task")
        if active_task:
            task_boundary = {
                "enabled": True,
                "task_name": active_task.get("name", "未命名任务"),
                "allowed_paths": active_task.get("allowed_paths", []),
                "forbidden_paths": active_task.get("forbidden_paths", []),
                "forbidden_keywords": active_task.get("forbidden_keywords", []),
            }

        # Evaluate risks.
        danger_info = None
        drift_info = None
        failure_info = None
        final_type = category
        source = f"hook_{event_name.lower()}"
        extra_summary = ""

        if category == "pretooluse":
            raw_text = parsed.get("raw_text", "")
            tool_name = parsed.get("tool_name", "")
            danger_info = evaluate_danger(tool_name, raw_text, risk_policy)
            drift_info = evaluate_drift(raw_text, task_boundary)

            if danger_info:
                final_type = "danger"
                source = "hook_pretooluse_danger"
            elif drift_info:
                final_type = "drift"
                source = "hook_pretooluse_drift"
            else:
                final_type = "info"
                source = "hook_pretooluse"

            # ── Approval detection ──────────────────────────────────────
            if approval_enabled and tool_name in candidate_tools:
                action_id = make_pending_action_id(parsed)
                summary = extract_tool_summary(parsed)
                tuid = extract_tool_identity(parsed)
                add_pending_action(action_id, tool_name, summary, tuid)
                print(f"[AgentWatch] Approval candidate registered: {tool_name}", flush=True)
                print(f"[AgentWatch] Waiting {delay_seconds}s to see whether PostToolUse arrives.", flush=True)

                # Spawn detached background checker.
                _spawn_pending_checker(action_id, delay_seconds)

        elif category == "posttooluse_error":
            failure_info = evaluate_failure(parsed, failure_policy)
            if failure_info:
                final_type = "failure"
                source = "hook_posttooluse_failure"
            else:
                final_type = "info"
                source = "hook_posttooluse_error"

        elif category == "posttooluse":
            from agentwatch.store import reset_failure_count
            reset_failure_count()
            final_type = "info"
            source = "hook_posttooluse"

            # ── Clear pending approval ──────────────────────────────────
            tuid = extract_tool_identity(parsed)
            tool_name = parsed.get("tool_name", "")
            cleared = clear_pending_action_by_match(tuid, tool_name)
            if cleared:
                print(f"[AgentWatch] Approval candidate cleared by PostToolUse: {cleared}", flush=True)

        elif event_name == "PermissionRequest":
            final_type = "permission_required"
            source = "hook_permission_request"
            print(f"[AgentWatch] PermissionRequest received — pushing notification.", flush=True)

        elif event_name == "PermissionDenied":
            final_type = "permission_denied"
            source = "hook_permission_denied"
            print(f"[AgentWatch] PermissionDenied received — logging only.", flush=True)

        elif category in ("permission_required", "attention_required"):
            final_type = category
            source = "hook_notification"

        elif category == "task_done":
            # Stop fires the instant the MAIN turn ends — even while background
            # work (background subagents / run_in_background Bash / Workflow) is
            # still running. Reporting "任务完成" then is a false positive, so when
            # the Stop payload lists active background tasks we downgrade to a
            # distinct, log-only event and let the *final* clean Stop (empty
            # background_tasks) deliver the real "完成".
            _BG_DONE_STATES = {"completed", "complete", "done", "failed", "error",
                               "cancelled", "canceled", "killed", "timeout", "stopped"}
            active_bg = [
                t for t in ((raw or {}).get("background_tasks") or [])
                if isinstance(t, dict)
                and str(t.get("status", "")).lower() not in _BG_DONE_STATES
            ]
            if active_bg:
                final_type = "task_done_pending_bg"
                source = "hook_stop_pending_bg"
                extra_summary = str(len(active_bg))
                print(
                    f"[AgentWatch] Stop fired with {len(active_bg)} background "
                    f"task(s) still running - not reporting done.",
                    file=sys.stderr, flush=True,
                )
            else:
                final_type = category
                source = "hook_stop"

        # Build message.
        msg = build_message(final_type, parsed, danger_info, drift_info, failure_info, extra_summary=extra_summary, config=config)

        # Decide whether to notify.
        notified = should_send_notification(final_type, npolicy)

        # Build log entry.
        log_entry = {
            "timestamp": parsed.get("timestamp", timestamp_iso()),
            "event_name": event_name,
            "event_type": final_type,
            "title": msg["title"],
            "body": msg["body"],
            "risk": (danger_info or drift_info or failure_info or {}).get("risk", "低"),
            "suggestion": (danger_info or drift_info or failure_info or {}).get("suggestion", ""),
            "notified": notified,
            "notification_mode": notification_mode,
            "source": source,
            "persona_theme": (config.get("persona", {}) or {}).get("theme", "off") if (config.get("persona", {}) or {}).get("enabled") else "off",
            "raw_event": raw or {},
        }
        append_event(log_entry)

        if notified and final_type != "info":
            send_bark(msg["title"], msg["body"], nc)

    except Exception as exc:
        print(f"[AgentWatch] ERROR in hook processing: {exc}", file=sys.stderr, flush=True)

    raise SystemExit(0)


def _spawn_pending_checker(action_id: str, delay_seconds: int) -> None:
    """Spawn a detached background process that checks whether *action_id*
    is still pending after *delay_seconds*, and notifies if so.

    Uses the current Python interpreter.  Failure is silent — never crashes
    the hook.
    """
    try:
        import subprocess

        python_exe = sys.executable
        # Use -m agentwatch.cli so it works regardless of PATH.
        cmd = [
            python_exe, "-m", "agentwatch.cli", "pending-check",
            "--id", action_id,
            "--delay", str(delay_seconds),
        ]
        # Detached: no stdio inheritance, start_new_session.
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        # Best-effort — if we can't spawn, the worst case is a missed notification.
        pass


# ---------------------------------------------------------------------------
# subcommands — task
# ---------------------------------------------------------------------------


def cmd_task_start(args: argparse.Namespace) -> None:
    """Set the current task boundary."""
    state = load_state()
    state["active_task"] = {
        "name": args.name,
        "allowed_paths": [p.strip() for p in args.allow.split(",") if p.strip()] if args.allow else [],
        "forbidden_paths": [p.strip() for p in args.forbid.split(",") if p.strip()] if args.forbid else [],
        "forbidden_keywords": [],
    }
    save_state(state)
    print(f"[AgentWatch] Task boundary set: {args.name}")
    _print_json(state["active_task"])


def cmd_task_clear() -> None:
    """Remove the current task boundary."""
    state = load_state()
    state.pop("active_task", None)
    save_state(state)
    print("[AgentWatch] Task boundary cleared.")


def cmd_task_status() -> None:
    """Show the current task boundary."""
    state = load_state()
    task = state.get("active_task")
    if task:
        print("[AgentWatch] Active task boundary:")
        _print_json(task)
    else:
        print("[AgentWatch] No active task boundary set.")


def cmd_task_quick() -> None:
    """Interactive task boundary setup."""
    print()
    print(f"{_ansi('bold')}AgentWatch — Quick Task Setup{_ansi('reset')}")
    print()

    # Task name
    try:
        name = input("Task name: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return
    if not name:
        print("Task name is required. Cancelled.")
        return

    # Defaults
    default_allowed = "tmp_agent_task,figures,results,scripts"
    default_forbidden = ".env,.git,config.json,agentwatch,pyproject.toml,README.md,install_claude_hooks.sh,uninstall_claude_hooks.sh"

    try:
        allowed_raw = input(f"Allowed paths [{default_allowed}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return
    allowed = [p.strip() for p in (allowed_raw or default_allowed).split(",") if p.strip()]

    try:
        forbidden_raw = input(f"Forbidden paths [{default_forbidden}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return
    forbidden = [p.strip() for p in (forbidden_raw or default_forbidden).split(",") if p.strip()]

    state = load_state()
    state["active_task"] = {
        "name": name,
        "allowed_paths": allowed,
        "forbidden_paths": forbidden,
        "forbidden_keywords": [],
    }
    save_state(state)

    print()
    print(f"{_ansi('green')}Saved.{_ansi('reset')}")
    _print_json(state["active_task"])


def cmd_logs(args: argparse.Namespace) -> None:
    """Print the last N log entries."""
    events = tail_logs(args.tail)
    if not events:
        print("[AgentWatch] No log entries yet.")
        return
    for ev in events:
        _print_json(ev)
        print("---")


def cmd_simulate(args: argparse.Namespace) -> None:
    """Simulate an event for testing classification and push."""
    scenario = args.scenario

    config = load_config()
    nc = get_notifier_config(config)
    npolicy = get_notification_policy(config)
    notification_mode = npolicy.get("mode", "actionable")
    force_notify = getattr(args, "notify", False)

    # ── permission-request: simulate PermissionRequest hook ─────────────
    if scenario == "permission-request":
        etype = "permission_required"
        msg = build_message(etype, parsed=None, config=config)
        notified = should_send_notification(etype, npolicy)
        print(f"[AgentWatch] Simulated PermissionRequest → {etype}")
        print(f"  Title: {msg['title']}")
        print(f"  Body:")
        for line in msg['body'].split("\n"):
            print(f"    {line}")

        log_entry = {
            "timestamp": timestamp_iso(), "event_name": "simulate",
            "event_type": etype, "title": msg["title"], "body": msg["body"],
            "risk": "中", "suggestion": "", "notified": notified,
            "notification_mode": notification_mode, "source": "hook_permission_request",
            "raw_event": {"scenario": scenario},
        }
        append_event(log_entry)
        if notified:
            ok = send_bark(msg["title"], msg["body"], nc)
            if ok: print(f"[AgentWatch] Notification sent: {msg['title']}")
            else: print("[AgentWatch] Notification failed.")
        return

    # ── permission-denied: simulate PermissionDenied hook ──────────────
    if scenario == "permission-denied":
        etype = "permission_denied"
        msg = build_message(etype, parsed=None, config=config)
        notified = should_send_notification(etype, npolicy)
        print(f"[AgentWatch] Simulated PermissionDenied → {etype}")
        print(f"  Title: {msg['title']}")
        print(f"  Body:")
        for line in msg['body'].split("\n"):
            print(f"    {line}")
        if not notified:
            print(f"[AgentWatch] Silent event logged: {etype} (no Watch push).")

        log_entry = {
            "timestamp": timestamp_iso(), "event_name": "simulate",
            "event_type": etype, "title": msg["title"], "body": msg["body"],
            "risk": "低", "suggestion": "已记录，无需操作", "notified": notified,
            "notification_mode": notification_mode, "source": "hook_permission_denied",
            "raw_event": {"scenario": scenario},
        }
        append_event(log_entry)
        return

    # ── approval-pending: simulate a PreToolUse that hangs ──────────────
    if scenario == "approval-pending":
        approval_cfg = config.get("approval_detection", {}) or {}
        delay = approval_cfg.get("delay_seconds", 4)
        timeout_notify = approval_cfg.get("timeout_watch_notify", False)
        action_id = f"sim_{timestamp_iso()}"
        summary = "Bash: cd ~/Projects/agentwatch && git status"

        add_pending_action(action_id, "Bash", summary)
        print("[AgentWatch] Approval candidate registered: Bash")
        print(f"[AgentWatch] Pending checker scheduled ({delay}s).")

        is_force = force_notify
        if is_force or timeout_notify:
            print("[AgentWatch] timeout_watch_notify=ON — will push if no PostToolUse arrives.")
        else:
            print("[AgentWatch] timeout_watch_notify=OFF — will log only (no Watch push).")

        import time as _time
        _time.sleep(delay)

        action = get_pending_action(action_id)
        if action and action.get("status") == "pending" and not action.get("notified"):
            # Decide event type based on config + --notify flag.
            if is_force or timeout_notify:
                etype = "permission_required"
                source = "pending_pretooluse_timeout"
                will_notify = True
            else:
                etype = "possible_permission_wait"
                source = "pending_pretooluse_timeout_log_only"
                will_notify = False

            msg = build_message(etype, extra_summary=summary, config=config)
            log_entry = {
                "timestamp": timestamp_iso(),
                "event_name": "simulate",
                "event_type": etype,
                "title": msg["title"],
                "body": msg["body"],
                "risk": "中" if etype == "permission_required" else "低",
                "suggestion": msg["body"].split("\n")[-1].replace("建议：", "") if "\n建议：" in msg["body"] else "",
                "notified": will_notify,
                "notification_mode": notification_mode,
                "source": source,
                "raw_event": {"scenario": scenario, "pending_action_id": action_id},
            }
            append_event(log_entry)
            mark_pending_notified(action_id)

            if will_notify:
                ok = send_bark(msg["title"], msg["body"], nc)
                if ok:
                    print(f"[AgentWatch] Notification sent: {msg['title']}")
                else:
                    print("[AgentWatch] Notification failed — check bark_key or network.")
            else:
                print(f"[AgentWatch] Pending timeout logged only.")
                print(f"[AgentWatch] No Watch notification sent because timeout_watch_notify=false.")
                print(f"[AgentWatch] Use --notify to force a push for testing.")
        else:
            print("[AgentWatch] Pending action already cleared — no notification.")
        return

    # ── auto-exec: simulate PreToolUse + PostToolUse clearing ────────────
    if scenario == "auto-exec":
        action_id = f"sim_{timestamp_iso()}"
        summary = "Bash: echo hello"
        add_pending_action(action_id, "Bash", summary)
        print("[AgentWatch] Approval candidate registered: Bash")
        print("[AgentWatch] Simulating PostToolUse after 1s...")

        import time as _time
        _time.sleep(1)

        cleared = clear_pending_action_by_match(tool_name="Bash")
        if cleared:
            print(f"[AgentWatch] Approval candidate cleared: {cleared}")
            print("[AgentWatch] No Watch notification should be sent.")
        else:
            print("[AgentWatch] Could not clear pending action (unexpected).")

        # Log an info event.
        log_entry = {
            "timestamp": timestamp_iso(),
            "event_name": "simulate",
            "event_type": "info",
            "title": "AgentWatch 提醒",
            "body": "Auto-exec simulation — pending action was cleared before timeout.",
            "risk": "低",
            "suggestion": "",
            "notified": False,
            "notification_mode": notification_mode,
            "source": "simulate",
            "raw_event": {"scenario": scenario},
        }
        append_event(log_entry)
        return

    # ── Existing scenarios ──────────────────────────────────────────────
    event_type = classify_simulated(scenario)

    parsed: dict[str, Any] = {
        "timestamp": timestamp_iso(),
        "event_name": "simulate",
        "raw_text": f"模拟场景: {scenario}",
        "tool_name": "simulate",
        "tool_input": {},
        "has_error": scenario == "failure",
        "parsed": True,
        "raw_event": {},
    }

    danger_info = None
    drift_info = None
    failure_info = None

    if scenario == "danger":
        danger_info = {
            "risk": "高",
            "matched_keywords": ["git push", ".env"],
            "suggestion": "立即回电脑确认",
        }
    elif scenario == "drift":
        state = load_state()
        task_name = (state.get("active_task") or {}).get("name", "生成论文图")
        drift_info = {
            "risk": "中",
            "task_name": task_name,
            "matched_boundary_violations": ["train"],
            "suggestion": "收窄任务或回电脑查看",
        }
    elif scenario == "failure":
        failure_info = {
            "risk": "中",
            "consecutive_failures": 3,
            "suggestion": "连续失败 3 次，可能卡住，请回电脑查看",
        }

    msg = build_message(event_type, parsed, danger_info, drift_info, failure_info, config=config)
    notified = force_notify or should_send_notification(event_type, npolicy)

    print(f"[AgentWatch] Simulated event: {scenario} → {event_type}")
    print(f"  Title: {msg['title']}")
    print(f"  Body:")
    for line in msg['body'].split("\n"):
        print(f"    {line}")

    log_entry = {
        "timestamp": parsed["timestamp"],
        "event_name": "simulate",
        "event_type": event_type,
        "title": msg["title"],
        "body": msg["body"],
        "risk": (danger_info or drift_info or failure_info or {}).get("risk", "低"),
        "suggestion": (danger_info or drift_info or failure_info or {}).get("suggestion", ""),
        "notified": notified,
        "notification_mode": notification_mode,
        "source": "simulate",
        "raw_event": {"scenario": scenario},
    }
    append_event(log_entry)

    if notified:
        ok = send_bark(msg["title"], msg["body"], nc)
        if ok:
            print(f"[AgentWatch] Notification sent: {msg['title']}")
        else:
            print("[AgentWatch] Notification failed — check bark_key or network.")
    else:
        print(f"[AgentWatch] Silent event logged: {event_type}")
        print(f"[AgentWatch] No Watch notification sent under {notification_mode} mode.")
        if scenario in ("danger", "drift", "failure"):
            print(f"[AgentWatch] Use --notify to force a push for testing.")


# ---------------------------------------------------------------------------
# new subcommand — doctor
# ---------------------------------------------------------------------------


def _check_hooks_readonly() -> str:
    """Check whether agentwatch hooks are present in ~/.claude/settings.json.

    Only *reads* the file — never modifies it.
    """
    if not _CLAUDE_SETTINGS.exists():
        return "Not detected (no settings file)"
    try:
        with open(_CLAUDE_SETTINGS, "r", encoding="utf-8") as fh:
            settings = json.load(fh)
    except Exception:
        return "Not detected (unparseable settings)"

    hooks = settings.get("hooks", {}) or {}
    found: list[str] = []
    for event_name in ["PreToolUse", "PostToolUse", "Notification", "Stop", "PermissionRequest", "PermissionDenied"]:
        groups = hooks.get(event_name, [])
        for g in groups:
            inner = g.get("hooks", []) if isinstance(g, dict) else []
            for h in inner:
                if isinstance(h, dict) and "agentwatch" in h.get("command", ""):
                    found.append(event_name)
                    break
            else:
                continue
            break

    if len(found) >= 6:
        return "Installed"
    if len(found) >= 4:
        return f"Partial (missing PermissionRequest)"
    if found:
        return f"Partial ({len(found)}/6)"
    return "Not installed"


def cmd_doctor() -> int:
    """Run a health check and return the number of issues found."""
    print()
    print(f"{_ansi('bold')}{_ansi('cyan')}AgentWatch Doctor{_ansi('reset')}")
    print()
    issues = 0

    # Project path
    project_dir = Path(__file__).resolve().parent.parent
    print(f"  Project:     {project_dir}")

    # Python
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 10)
    tag = _ansi("green") + "OK" + _ansi("reset") if py_ok else _ansi("red") + "WARN" + _ansi("reset")
    print(f"  Python:      {tag} (v{py_ver})")
    if not py_ok:
        issues += 1

    # Config
    if CONFIG_FILE.exists():
        try:
            config = load_config()
            nc = get_notifier_config(config)
            bark_key = nc.get("bark_key", "")
            bark_ok = bark_key and bark_key != "YOUR_BARK_KEY"
            bark_display = mask_key(bark_key) if bark_ok else "NOT SET"
            tag2 = _ansi("green") + "OK" + _ansi("reset") if bark_ok else _ansi("red") + "WARN" + _ansi("reset")
            print(f"  Config:      OK")
            print(f"  Bark:        {tag2}, key = {bark_display}")
            if not bark_ok:
                issues += 1
        except Exception:
            print(f"  Config:      {_ansi('red')}ERROR (unparseable){_ansi('reset')}")
            issues += 1
            return issues
    else:
        print(f"  Config:      {_ansi('red')}MISSING{_ansi('reset')}")
        print(f"               Run 'agentwatch init' first.")
        issues += 1
        return issues

    # Logs
    if EVENTS_LOG.exists():
        # Also show the last event if available
        last_info = ""
        events = tail_logs(1)
        if events and "timestamp" in events[0]:
            ts = events[0]["timestamp"][:19].replace("T", " ")
            et = events[0].get("event_type", "?")
            last_info = f"  |  Last: {ts} / {et}"
        print(f"  Logs:        {_ansi('green')}OK{_ansi('reset')}{last_info}")
    else:
        print(f"  Logs:        {_ansi('yellow')}No events yet{_ansi('reset')}")

    # Claude hooks (read-only check)
    hook_status = _check_hooks_readonly()
    if hook_status == "Installed":
        print(f"  Claude hooks:{_ansi('green')}Installed{_ansi('reset')}")
    elif "missing PermissionRequest" in hook_status:
        print(f"  Claude hooks:{_ansi('yellow')}Missing PermissionRequest{_ansi('reset')}")
        print(f"               Run install script again to add PermissionRequest/PermissionDenied hooks.")
        issues += 1
    elif hook_status.startswith("Partial"):
        print(f"  Claude hooks:{_ansi('yellow')}{hook_status}{_ansi('reset')}")
        issues += 1
    else:
        print(f"  Claude hooks:{_ansi('yellow')}{hook_status}{_ansi('reset')}")
        print(f"               Run: bash install_claude_hooks.sh")
        issues += 1

    # Active task
    state = load_state()
    task = state.get("active_task")
    if task:
        print(f"  Task:        {task.get('name', '?')}")
    else:
        print(f"  Task:        (none)")

    # Summary
    print()
    if issues == 0:
        print(f"  {_ansi('green')}{_ansi('bold')}Status: Ready{_ansi('reset')}")
    else:
        print(f"  {_ansi('yellow')}{_ansi('bold')}Status: {issues} issue(s) found{_ansi('reset')}")
    print()
    return issues


# ---------------------------------------------------------------------------
# new subcommand — monitor
# ---------------------------------------------------------------------------


def _fmt_event_row(ev: dict[str, Any]) -> str:
    """Format one log entry as a single-line monitor row."""
    ts = ev.get("timestamp", "")[:19].replace("T", " ")[-8:]  # HH:MM:SS
    etype = ev.get("event_type", "?")
    title = ev.get("title", "")
    risk = ev.get("risk", "低")
    body_line = (ev.get("body", "") or "").split("\n")[0]
    if len(body_line) > 50:
        body_line = body_line[:47] + "..."

    icon_map = {
        "danger": "⚠",
        "drift": "↗",
        "failure": "✗",
        "task_done": "✓",
        "task_done_pending_bg": "⏳",
        "attention_required": "‼",
        "permission_required": "‼",
        "info": "·",
    }
    icon = icon_map.get(etype, "·")
    color = _risk_color(risk)
    return f"  {_ansi('dim')}{ts}{_ansi('reset')}  {icon}  {color}{title:<16}{_ansi('reset')} {_ansi('dim')}|{_ansi('reset')} {body_line}"


def _render_monitor(config: dict[str, Any], issues: int) -> str:
    """Build the monitor display string."""
    lines: list[str] = []
    b = _ansi("bold")
    r = _ansi("reset")
    c = _ansi("cyan")
    g = _ansi("green")
    y = _ansi("yellow")
    d = _ansi("dim")

    lines.append(f"{_ansi('clear')}")
    lines.append(f"{b}{c}  AgentWatch Monitor{r}")
    lines.append(f"  {d}{'─' * 58}{r}")
    lines.append("")

    # Status block
    nc = get_notifier_config(config)
    bark_ok = bool(nc.get("bark_key", "") and nc["bark_key"] != "YOUR_BARK_KEY")
    hook_status = _check_hooks_readonly()
    hooks_ok = hook_status == "Installed"

    lines.append(f"  {b}Status:{r}")
    lines.append(f"    Bark:         {g}OK{r}" if bark_ok else f"    Bark:         {y}NOT CONFIGURED{r}")
    lines.append(f"    Hooks:        {g}{hook_status}{r}" if hooks_ok else f"    Hooks:        {y}{hook_status}{r}")

    state = load_state()
    task = state.get("active_task")
    if task:
        lines.append(f"    Current task: {task.get('name', '?')}")
        allowed = task.get("allowed_paths", [])
        forbidden = task.get("forbidden_paths", [])
        if allowed:
            lines.append(f"    Allowed:      {', '.join(allowed[:5])}")
        if forbidden:
            lines.append(f"    Forbidden:    {', '.join(forbidden[:5])}")
    else:
        lines.append(f"    Current task: {d}(none){r}")

    lines.append("")

    # Recent events
    lines.append(f"  {b}Recent events:{r}")
    events = tail_logs(10)
    if events:
        for ev in reversed(events):
            if ev.get("event_type") != "info":
                lines.append(_fmt_event_row(ev))
    else:
        lines.append(f"    {d}(no events yet){r}")

    lines.append("")

    # Tips
    lines.append(f"  {b}Tips:{r}")
    lines.append(f"    {d}Press Ctrl+C to exit monitor.{r}")
    lines.append(f"    {d}Hooks work even if this monitor is closed.{r}")
    lines.append(f"    {d}Start task boundary: agentwatch task quick{r}")

    lines.append("")
    return "\n".join(lines)


def cmd_monitor() -> None:
    """Launch an ANSI live-monitor dashboard.  Ctrl+C to exit."""
    print(f"{_ansi('clear')}AgentWatch Monitor — starting ...", flush=True)
    running = True

    def _on_sigint(_sig: int, _frame: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _on_sigint)

    # Load config once — if it fails, report and exit.
    try:
        config = load_config()
    except SystemExit:
        print("Cannot start monitor without valid config. Run 'agentwatch init' first.")
        return

    while running:
        try:
            # Re-count issues each loop so status is live.
            nc = get_notifier_config(config)
            bark_ok = bool(nc.get("bark_key", "") and nc["bark_key"] != "YOUR_BARK_KEY")
            hooks_ok = _check_hooks_readonly() == "Installed"
            issues = 0 if (bark_ok and hooks_ok) else 1

            display = _render_monitor(config, issues)
            sys.stdout.write(display)
            sys.stdout.flush()
            time.sleep(2)
        except Exception:
            time.sleep(2)

    # Clean exit
    print(f"{_ansi('clear')}AgentWatch Monitor closed.{_ansi('reset')}")
    print("Hooks continue to work in the background.")
    print()


# ---------------------------------------------------------------------------
# new subcommand — start
# ---------------------------------------------------------------------------


def cmd_start() -> None:
    """Entry point for end users: doctor check → monitor."""
    issues = cmd_doctor()

    if issues > 0:
        print(f"{_ansi('yellow')}Some issues were detected. You can still enter monitor mode.{_ansi('reset')}")
        print()
        try:
            ans = input("Continue to monitor? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            return
        if ans and ans not in ("y", "yes", ""):
            print("Exiting.")
            return

    print("Entering monitor mode ...")
    print()
    cmd_monitor()


# ---------------------------------------------------------------------------
# subcommand — config
# ---------------------------------------------------------------------------


def cmd_config_bark(args: argparse.Namespace) -> None:
    """Set the Bark key (interactive or via --value)."""
    # Ensure config.json exists.
    if not CONFIG_FILE.exists():
        init_config()

    config = load_config()
    nc = config.setdefault("notifier", {})

    # Get input: from --value or prompt.
    value = ""
    if hasattr(args, "value") and args.value:
        value = args.value.strip()
    if not value:
        print()
        print(f"{_ansi('bold')}AgentWatch — Configure Bark Key{_ansi('reset')}")
        print()
        print("Paste your Bark URL or Bark Key:")
        print("  Examples:")
        print("    https://api.day.app/YOUR_KEY/")
        print("    YOUR_KEY")
        print()
        try:
            value = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return

    if not value:
        print("Empty input — cancelled.")
        return

    # Parse.
    try:
        parsed_server, parsed_key = parse_bark_input(value)
    except ValueError as exc:
        print(f"{_ansi('red')}Error:{_ansi('reset')} {exc}")
        return

    # Determine server.
    if parsed_server:
        nc["bark_server"] = parsed_server
    else:
        nc.setdefault("bark_server", "https://api.day.app")

    # Set the key.
    nc["bark_key"] = parsed_key

    # Write back.
    config["notifier"] = nc
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)

    print()
    print(f"{_ansi('green')}Bark key updated:{_ansi('reset')} {mask_key(parsed_key)}")
    print(f"Server: {nc.get('bark_server', 'https://api.day.app')}")
    print()
    print("Run 'agentwatch config test' or 'agentwatch test-push' to verify.")


def cmd_config_show() -> None:
    """Display current Bark configuration."""
    print()
    print(f"{_ansi('bold')}{_ansi('cyan')}AgentWatch Config{_ansi('reset')}")
    print()

    if not CONFIG_FILE.exists():
        print("  Config file not found. Run 'agentwatch init' first.")
        return

    try:
        config = load_config()
    except SystemExit:
        return

    nc = get_notifier_config(config)
    bark_key = nc.get("bark_key", "")
    bark_ok = bool(bark_key and bark_key != "YOUR_BARK_KEY")
    server = nc.get("bark_server", "https://api.day.app")

    tag = _ansi("green") + "OK" + _ansi("reset") if bark_ok else _ansi("red") + "Missing" + _ansi("reset")
    print(f"  Bark:    {tag}")
    print(f"  Server:  {server}")
    print(f"  Key:     {mask_key(bark_key) if bark_ok else 'Not configured'}")
    print()


def cmd_config_test() -> None:
    """Send a Bark test notification (semantic alias for test-push)."""
    config = load_config()
    nc = get_notifier_config(config)
    key = nc.get("bark_key", "")
    print(f"[AgentWatch] Using bark_key: {mask_key(key)}")
    print("[AgentWatch] Sending test notification ...")

    ok = send_bark(
        "AgentWatch Bark 测试",
        "Bark Key 已配置成功。如果你在 Apple Watch 上看到这条消息，说明链路已打通。",
        nc,
    )
    if ok:
        print("[AgentWatch] Test notification sent. Check your iPhone / Apple Watch.")
    else:
        print("[AgentWatch] Failed to send notification. Check your bark_key and network.")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# subcommand — pending-check (internal, called by background checker)
# ---------------------------------------------------------------------------


def cmd_pending_check(args: argparse.Namespace) -> None:
    """Background checker: sleep, then inspect a pending action and notify if needed."""
    action_id = args.id
    delay = int(args.delay)

    try:
        import time
        time.sleep(delay)
    except KeyboardInterrupt:
        raise SystemExit(0)

    action = get_pending_action(action_id)
    if not action:
        # Already cleaned up or never existed.
        raise SystemExit(0)

    if action.get("status") != "pending":
        raise SystemExit(0)

    if action.get("notified"):
        raise SystemExit(0)

    # Still pending after delay → decide whether to notify or log-only.
    config = load_config()
    nc = get_notifier_config(config)
    npolicy = get_notification_policy(config)
    notification_mode = npolicy.get("mode", "actionable")
    approval_cfg = config.get("approval_detection", {}) or {}

    timeout_notify = approval_cfg.get("timeout_watch_notify", False)
    summary = action.get("summary", "等待用户允许操作")
    tool_name = action.get("tool_name", "")

    if timeout_notify:
        # User has opted in to timeout → push permission_required (respects persona).
        etype = "permission_required"
        source = "pending_pretooluse_timeout"
        msg = build_message(etype, extra_summary=summary, config=config)
        notified = True
    else:
        # Default: log-only (possible_permission_wait).  No Watch push.
        etype = "possible_permission_wait"
        source = "pending_pretooluse_timeout_log_only"
        msg = build_message(etype, extra_summary=summary, config=config)
        notified = False

    # Log the event.
    log_entry = {
        "timestamp": timestamp_iso(),
        "event_name": "pending_check",
        "event_type": etype,
        "title": msg["title"],
        "body": msg["body"],
        "risk": "低" if etype == "possible_permission_wait" else "中",
        "suggestion": msg["body"].split("\n")[-1].replace("建议：", "") if "\n建议：" in msg["body"] else "",
        "notified": notified,
        "notification_mode": notification_mode,
        "source": source,
        "raw_event": {
            "pending_action_id": action_id,
            "tool_name": tool_name,
            "summary": summary,
        },
    }
    append_event(log_entry)

    # Mark as notified (even log-only, so we don't re-process).
    mark_pending_notified(action_id)

    if notified:
        send_bark(msg["title"], msg["body"], nc)

    raise SystemExit(0)


from agentwatch.persona import get_persona_config, theme_display_name, valid_themes, apply_persona as _apply_persona

# ---------------------------------------------------------------------------
# subcommand — persona
# ---------------------------------------------------------------------------

_VALID_THEMES = valid_themes()


def _write_persona_config(theme: str) -> None:
    """Write persona config into config.json, preserving all other fields."""
    if not CONFIG_FILE.exists():
        init_config()
    config = load_config()
    pc = get_persona_config(config)
    pc["enabled"] = theme != "off"
    pc["theme"] = theme
    config["persona"] = pc
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)


def cmd_persona_show() -> None:
    """Display current persona configuration."""
    print()
    print(f"{_ansi('bold')}{_ansi('cyan')}AgentWatch Persona{_ansi('reset')}")
    print()
    if not CONFIG_FILE.exists():
        print("  No config.json — run 'agentwatch init' first.")
        return
    config = load_config()
    pc = get_persona_config(config)
    theme = pc.get("theme", "off")
    enabled = pc.get("enabled", False)
    display = theme_display_name(theme) if enabled else "Off"
    print(f"  Persona:  {display}")
    if enabled and theme != "off":
        print(f"  Theme:    {theme}")
    print("  Available themes:")
    for t in _VALID_THEMES:
        marker = " ←" if t == theme and enabled else ""
        name = theme_display_name(t)
        print(f"    {name}{marker}")
    print()


def cmd_persona_set(theme: str) -> None:
    """Set the persona theme."""
    if theme not in _VALID_THEMES:
        print(f"{_ansi('red')}Invalid theme:{_ansi('reset')} {theme}")
        print(f"  Valid themes: {', '.join(_VALID_THEMES)}")
        raise SystemExit(1)
    _write_persona_config(theme)
    name = theme_display_name(theme)
    print(f"{_ansi('green')}Persona theme updated:{_ansi('reset')} {name}")


def cmd_persona_off() -> None:
    """Turn off persona (use default messages)."""
    _write_persona_config("off")
    print(f"{_ansi('green')}Persona disabled.{_ansi('reset')} Using default notification text.")


def cmd_persona_test(event_type: str) -> None:
    """Preview persona text for a specific event type (no Bark push)."""
    print()
    print(f"{_ansi('bold')}{_ansi('cyan')}AgentWatch Persona Preview{_ansi('reset')}")
    print()

    if not CONFIG_FILE.exists():
        print("  No config.json — run 'agentwatch init' first.")
        return

    config = load_config()
    pc = get_persona_config(config)
    theme = pc.get("theme", "off")
    name = theme_display_name(theme)

    print(f"  Persona:  {name}")
    print(f"  Event:    {event_type}")
    print()

    from agentwatch.message_builder import TITLE_MAP
    std_title = TITLE_MAP.get(event_type, "AgentWatch 提醒")
    std_body = "标准文案（非 persona）"
    persona_title, persona_body = _apply_persona(event_type, std_title, std_body, config)

    if persona_title == std_title and persona_body == std_body:
        print(f"  {_ansi('yellow')}No persona template for this event type.{_ansi('reset')}")
        print(f"  Would use standard message.")
    else:
        print(f"  {_ansi('bold')}Title:{_ansi('reset')} {persona_title}")
        print(f"  {_ansi('bold')}Body:{_ansi('reset')}")
        for line in persona_body.split("\n"):
            print(f"    {line}")
    print()
    print("  (No notification was sent — this is a preview only.)")
    print()


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentwatch",
        description="Claude Code / AI Agent status monitor with Apple Watch notifications",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # init
    sub.add_parser("init", help="Initialise config and log directory")

    # test-push
    sub.add_parser("test-push", help="Send a test Bark notification")

    # doctor
    sub.add_parser("doctor", help="Run health check")

    # monitor
    sub.add_parser("monitor", help="Launch live monitoring dashboard (Ctrl+C to exit)")

    # start
    sub.add_parser("start", help="Doctor check + monitor (one-click entry point)")

    # config
    p_config = sub.add_parser("config", help="Manage AgentWatch configuration")
    config_sub = p_config.add_subparsers(dest="config_cmd")

    p_bark = config_sub.add_parser("bark", help="Set Bark key (interactive or --value)")
    p_bark.add_argument("--value", default="", help="Bark URL or key to set (non-interactive)")

    config_sub.add_parser("show", help="Show current Bark configuration")
    config_sub.add_parser("test", help="Send a Bark test notification")

    # persona
    p_persona = sub.add_parser("persona", help="Manage notification persona themes")
    persona_sub = p_persona.add_subparsers(dest="persona_cmd")

    persona_sub.add_parser("show", help="Show current persona theme")
    persona_sub.add_parser("off", help="Disable persona (use default messages)")

    p_set = persona_sub.add_parser("set", help="Set persona theme")
    p_set.add_argument("theme", choices=["boss", "heir_male", "heir_female", "emperor", "palace"])

    p_test = persona_sub.add_parser("test", help="Preview persona text without pushing")
    p_test.add_argument("event", choices=["permission", "done", "danger", "drift", "failure"])

    # hook
    p_hook = sub.add_parser("hook", help="Claude Code hook entry point (called by hooks)")
    p_hook.add_argument("--event", required=True, choices=["PreToolUse", "PostToolUse", "Notification", "Stop", "PermissionRequest", "PermissionDenied"])

    # task
    p_task = sub.add_parser("task", help="Manage task boundaries")
    task_sub = p_task.add_subparsers(dest="task_cmd")

    p_start = task_sub.add_parser("start", help="Set current task boundary (CLI flags)")
    p_start.add_argument("--name", required=True, help="Task name")
    p_start.add_argument("--allow", default="", help="Comma-separated allowed paths")
    p_start.add_argument("--forbid", default="", help="Comma-separated forbidden paths/keywords")

    task_sub.add_parser("quick", help="Interactive task boundary setup")
    task_sub.add_parser("clear", help="Clear current task boundary")
    task_sub.add_parser("status", help="Show current task boundary")

    # logs
    p_logs = sub.add_parser("logs", help="View recent event logs")
    p_logs.add_argument("--tail", type=int, default=20, help="Number of recent entries (default: 20)")

    # simulate
    p_sim = sub.add_parser("simulate", help="Simulate an event for testing")
    p_sim.add_argument("scenario", choices=[
        "danger", "done", "drift", "failure", "permission",
        "permission-request", "permission-denied",
        "approval-pending", "auto-exec",
    ])
    p_sim.add_argument("--notify", action="store_true", help="Force push notification even in actionable mode")

    # pending-check (internal command, spawned by hooks)
    p_pc = sub.add_parser("pending-check", help="[Internal] Background approval checker")
    p_pc.add_argument("--id", required=True, help="Pending action ID")
    p_pc.add_argument("--delay", type=int, default=4, help="Seconds to wait before checking")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        cmd_init()
    elif args.command == "test-push":
        cmd_test_push()
    elif args.command == "doctor":
        cmd_doctor()
    elif args.command == "monitor":
        cmd_monitor()
    elif args.command == "start":
        cmd_start()
    elif args.command == "config":
        if args.config_cmd == "bark":
            cmd_config_bark(args)
        elif args.config_cmd == "show":
            cmd_config_show()
        elif args.config_cmd == "test":
            cmd_config_test()
        else:
            parser.parse_args(["config", "--help"])
    elif args.command == "persona":
        if args.persona_cmd == "show":
            cmd_persona_show()
        elif args.persona_cmd == "set":
            cmd_persona_set(args.theme)
        elif args.persona_cmd == "off":
            cmd_persona_off()
        elif args.persona_cmd == "test":
            # Map short event names to internal event_types.
            event_map = {
                "permission": "permission_required",
                "done": "task_done",
                "danger": "danger",
                "drift": "drift",
                "failure": "failure",
            }
            cmd_persona_test(event_map.get(args.event, args.event))
        else:
            parser.parse_args(["persona", "--help"])
    elif args.command == "hook":
        cmd_hook(args.event)
    elif args.command == "task":
        if args.task_cmd == "start":
            cmd_task_start(args)
        elif args.task_cmd == "quick":
            cmd_task_quick()
        elif args.task_cmd == "clear":
            cmd_task_clear()
        elif args.task_cmd == "status":
            cmd_task_status()
        else:
            parser.parse_args(["task", "--help"])
    elif args.command == "logs":
        cmd_logs(args)
    elif args.command == "simulate":
        cmd_simulate(args)
    elif args.command == "pending-check":
        cmd_pending_check(args)
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
