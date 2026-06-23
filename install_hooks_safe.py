"""Safely merge AgentWatch hooks into ~/.claude/settings.json.

Uses Python's json module (preserves single-element arrays, unlike PS 5.1
ConvertTo-Json which collapses them). Backs up first. Idempotent: re-running
removes old agentwatch entries before re-adding, never touching other hooks.
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"
EVENTS = ["PreToolUse", "PostToolUse", "Notification", "Stop",
          "PermissionRequest", "PermissionDenied"]


def resolve_python(cli_python: str | None = None) -> str:
    """Resolve the Python interpreter to embed in the hook command.

    Priority: --python CLI arg > AGENTWATCH_PYTHON env var > sys.executable.
    sys.executable points at the interpreter running this installer, so running
    it from the same environment AgentWatch is installed in (your venv, or after
    `pip install agentwatch`) makes the hooks use the right Python with no config.
    Returned as a POSIX-style path so it embeds cleanly in JSON on Windows too.
    """
    candidate = cli_python or os.environ.get("AGENTWATCH_PYTHON") or sys.executable
    return Path(candidate).as_posix()


def make_group(event: str, python_bin: str) -> dict:
    return {
        "hooks": [
            {
                "type": "command",
                "command": f'"{python_bin}" -m agentwatch.cli hook --event {event}',
                "timeout": 15,
            }
        ]
    }


def has_agentwatch(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    if "agentwatch" in entry.get("command", ""):
        return True
    inner = entry.get("hooks", [])
    if isinstance(inner, list):
        return any(
            isinstance(h, dict) and "agentwatch" in h.get("command", "")
            for h in inner
        )
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely merge AgentWatch hooks into ~/.claude/settings.json."
    )
    parser.add_argument(
        "--python",
        help="Python interpreter to run the hooks with "
        "(default: AGENTWATCH_PYTHON env var, else the interpreter running this script).",
    )
    args = parser.parse_args()
    python_bin = resolve_python(args.python)
    print(f"[AgentWatch] Hook interpreter: {python_bin}")

    if not SETTINGS.exists():
        raise SystemExit(f"settings.json not found at {SETTINGS}")

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = SETTINGS.with_name(f"settings.json.agentwatch.bak.{ts}")
    shutil.copy(SETTINGS, backup)
    print(f"[AgentWatch] Backed up to: {backup}")

    with open(SETTINGS, "r", encoding="utf-8-sig") as fh:
        settings = json.load(fh)

    hooks = settings.get("hooks", {}) or {}
    modified = []
    for event in EVENTS:
        existing = hooks.get(event, []) or []
        cleaned = [e for e in existing if not has_agentwatch(e)]
        hooks[event] = cleaned + [make_group(event, python_bin)]
        modified.append(event)

    settings["hooks"] = hooks
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, ensure_ascii=False, indent=2)

    print(f"[AgentWatch] Hooks installed for: {', '.join(modified)}")
    print(f"[AgentWatch] Written (UTF-8, no BOM): {SETTINGS}")


if __name__ == "__main__":
    main()
