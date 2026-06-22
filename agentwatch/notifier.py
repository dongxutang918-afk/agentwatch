"""Send notifications via Bark / Pushover / ntfy.

All backends share the (title, body, notifier_config) -> bool interface and
NEVER raise — hooks always exit 0. Use :func:`dispatch` to route by
``notifier_config["type"]``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from agentwatch.utils import url_encode


def send_bark(title: str, body: str, notifier_config: dict[str, Any]) -> bool:
    """Push a notification through the Bark API.

    Returns True on success, False on failure.
    The caller MUST NOT crash on False — hooks always exit 0.
    """
    bark_key = notifier_config.get("bark_key", "")
    if not bark_key or bark_key == "YOUR_BARK_KEY":
        print("[AgentWatch] WARN: bark_key is not configured. Skipping push.")
        return False

    bark_server = notifier_config.get("bark_server", "https://api.day.app").rstrip("/")
    group = notifier_config.get("group", "AgentWatch")
    level = notifier_config.get("level", "timeSensitive")

    # Build the Bark URL.
    encoded_title = url_encode(title)
    encoded_body = url_encode(body)
    url = (
        f"{bark_server}/{bark_key}/{encoded_title}/{encoded_body}"
        f"?group={url_encode(group)}&level={url_encode(level)}"
    )

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 200:
                return True
            else:
                print(f"[AgentWatch] Bark API returned: {data}", flush=True)
                return False
    except urllib.error.HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        print(f"[AgentWatch] Bark push failed (HTTP {exc.code}): {body_text or exc.reason}", flush=True)
        return False
    except Exception as exc:
        print(f"[AgentWatch] Bark push failed: {exc}", flush=True)
        return False


def _report_http_failure(backend: str, exc: Exception) -> None:
    """Log an HTTP/network failure for a push backend. Never raises."""
    if isinstance(exc, urllib.error.HTTPError):
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        print(f"[AgentWatch] {backend} push failed (HTTP {exc.code}): {detail or exc.reason}", flush=True)
    else:
        print(f"[AgentWatch] {backend} push failed: {exc}", flush=True)


def send_pushover(title: str, body: str, notifier_config: dict[str, Any]) -> bool:
    """Push through the Pushover API. Returns True on success, False on failure."""
    token = notifier_config.get("pushover_token", "")
    user = notifier_config.get("pushover_user", "")
    if not token or token == "YOUR_PUSHOVER_TOKEN" or not user or user == "YOUR_PUSHOVER_USER":
        print("[AgentWatch] WARN: pushover_token/pushover_user not configured. Skipping push.")
        return False

    server = notifier_config.get("pushover_server", "https://api.pushover.net").rstrip("/")
    fields: dict[str, str] = {"token": token, "user": user, "title": title, "message": body}
    priority = notifier_config.get("pushover_priority")
    if priority is not None:
        fields["priority"] = str(priority)

    data = urllib.parse.urlencode(fields).encode("utf-8")
    url = f"{server}/1/messages.json"
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            if resp_data.get("status") == 1:
                return True
            print(f"[AgentWatch] Pushover API returned: {resp_data}", flush=True)
            return False
    except Exception as exc:
        _report_http_failure("Pushover", exc)
        return False


def send_ntfy(title: str, body: str, notifier_config: dict[str, Any]) -> bool:
    """Push through ntfy via the JSON publishing endpoint.

    JSON publishing (POST {topic,title,message} to the server root) is used
    instead of the per-topic endpoint so UTF-8 titles travel in the body
    rather than a latin-1 HTTP header. Returns True on success.
    """
    topic = notifier_config.get("ntfy_topic", "")
    if not topic or topic == "YOUR_NTFY_TOPIC":
        print("[AgentWatch] WARN: ntfy_topic is not configured. Skipping push.")
        return False

    server = notifier_config.get("ntfy_server", "https://ntfy.sh").rstrip("/")
    payload: dict[str, Any] = {
        "topic": topic,
        "title": title,
        "message": body,
        "priority": notifier_config.get("ntfy_priority", 4),
    }
    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(server, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        token = notifier_config.get("ntfy_token", "")
        if token and token != "YOUR_NTFY_TOKEN":
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()  # any 2xx counts as delivered
            return True
    except Exception as exc:
        _report_http_failure("ntfy", exc)
        return False


def dispatch(title: str, body: str, notifier_config: dict[str, Any]) -> bool:
    """Route a push to the backend named by ``notifier_config["type"]``.

    Defaults to (and falls back to) Bark for unknown/missing types.
    """
    ntype = notifier_config.get("type", "bark")
    if ntype == "pushover":
        return send_pushover(title, body, notifier_config)
    if ntype == "ntfy":
        return send_ntfy(title, body, notifier_config)
    if ntype != "bark":
        print(f"[AgentWatch] WARN: unknown notifier.type '{ntype}', falling back to bark.")
    return send_bark(title, body, notifier_config)
