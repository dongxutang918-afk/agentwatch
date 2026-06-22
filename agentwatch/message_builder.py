"""Build human-readable Watch notification titles and bodies."""

from __future__ import annotations

from typing import Any

from agentwatch.persona import apply_persona, persona_summary_lead


# Mapping from event_type to notification title and body template logic.
TITLE_MAP = {
    "permission_required": "需要权限",
    "attention_required": "Agent 需要你处理",
    "task_done": "任务完成",
    "session_summary": "本次会话小结",
    "danger": "高风险操作",
    "drift": "可能跑偏",
    "failure": "可能卡住",
    "possible_permission_wait": "疑似等待权限",
    "permission_denied": "权限已拒绝",
}


def build_message(
    event_type: str,
    parsed: dict[str, Any] | None = None,
    danger_info: dict[str, Any] | None = None,
    drift_info: dict[str, Any] | None = None,
    failure_info: dict[str, Any] | None = None,
    extra_summary: str = "",
    config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Generate a Watch notification {title, body}.

    Parameters
    ----------
    event_type : str
        One of permission_required, attention_required, task_done, danger, drift, failure.
    The *_info dicts carry optional detail from policy evaluation.
    extra_summary : str
        Optional tool summary for permission_required body (e.g. "Bash: cd ~/...")
    config : dict | None
        Optional config dict for persona overlay.
    """
    title = TITLE_MAP.get(event_type, "AgentWatch 提醒")
    body = _build_body(event_type, parsed, danger_info, drift_info, failure_info, extra_summary)

    # Apply persona overlay if configured.
    if config is not None:
        if event_type == "session_summary":
            # The digest body is dynamic (tool counts, file names), so persona
            # only swaps the title and prepends a one-line lead — never replaces
            # the metric lines the way apply_persona would.
            p_title, p_lead = persona_summary_lead(config)
            if p_title:
                title = p_title
            if p_lead:
                body = f"{p_lead}\n{body}"
        else:
            title, body = apply_persona(event_type, title, body, config)

    return {"title": title, "body": body}


def _build_body(
    event_type: str,
    parsed: dict[str, Any] | None,
    danger_info: dict[str, Any] | None,
    drift_info: dict[str, Any] | None,
    failure_info: dict[str, Any] | None,
    extra_summary: str = "",
) -> str:
    if event_type == "permission_required":
        return _body_permission(parsed, extra_summary)
    if event_type == "attention_required":
        return _body_attention(parsed)

    if event_type == "task_done":
        return _body_done(parsed)

    if event_type == "session_summary":
        return _body_session_summary(extra_summary)

    if event_type == "danger":
        return _body_danger(danger_info)

    if event_type == "drift":
        return _body_drift(drift_info)

    if event_type == "failure":
        return _body_failure(failure_info)

    if event_type == "possible_permission_wait":
        return _body_possible_wait(extra_summary)

    if event_type == "permission_denied":
        return _body_permission_denied(parsed)

    return "AgentWatch 事件"


def _body_possible_wait(extra_summary: str = "") -> str:
    """Build body for possible_permission_wait — uncertain if user action needed."""
    tool_info = extra_summary or "待确认"
    if len(tool_info) > 80:
        tool_info = tool_info[:77] + "..."
    return (
        f"Agent 的工具调用尚未返回，可能在等待权限，也可能仍在执行。\n"
        f"操作：{tool_info}\n"
        f"风险：低\n"
        f"建议：有空时回电脑看一眼。"
    )


def _body_permission(parsed: dict[str, Any] | None, extra_summary: str = "") -> str:
    """Build body for permission_required — tool is waiting for user approval."""
    summary = extra_summary or "等待用户允许操作"
    if len(summary) > 80:
        summary = summary[:77] + "..."
    return (
        f"Agent 正在等待你允许操作\n"
        f"操作：{summary}\n"
        f"风险：中\n"
        f"建议：回电脑点击 Allow / Yes"
    )


def _body_attention(parsed: dict[str, Any] | None) -> str:
    raw = parsed or {}
    notification = raw.get("raw_event", {}).get("notification", {})
    title = notification.get("title", "") or notification.get("message", "") or "Agent 请求你的注意"
    msg = notification.get("message", "") or notification.get("body", "") or "Agent 需要介入处理"

    summary = f"Agent 请求注意：{title}"
    if len(summary) > 80:
        summary = summary[:77] + "..."

    return f"{summary}\n风险：中\n建议：回电脑查看发生了什么"


def _body_done(parsed: dict[str, Any] | None) -> str:
    raw = parsed or {}
    stop_reason = raw.get("raw_event", {}).get("reason", "") or "当前步骤已结束"
    return f"Claude Code 当前步骤已结束：{stop_reason}\n风险：低\n建议：回电脑验收或给下一步指示"


def _body_session_summary(extra_summary: str = "") -> str:
    """Body for session_summary.

    *extra_summary* is the digest already rendered by
    :func:`agentwatch.session_summary.render_summary_body` (the metric lines plus
    风险 / 建议).  We pass it through verbatim, with a defensive fallback.
    """
    return extra_summary.strip() or (
        "本次会话已结束。\n风险：低\n建议：回电脑验收或给下一步指示"
    )


def _body_danger(danger_info: dict[str, Any] | None) -> str:
    if not danger_info:
        return "检测到高风险操作\n风险：高\n建议：立即回电脑确认"
    keywords = danger_info.get("matched_keywords", [])
    kw_str = ", ".join(keywords[:3])
    risk = danger_info.get("risk", "高")
    suggestion = danger_info.get("suggestion", "立即回电脑确认")
    tool_info = f"Agent 试图执行涉及 {kw_str} 的操作"
    if len(tool_info) > 80:
        tool_info = tool_info[:77] + "..."
    return f"{tool_info}\n风险：{risk}\n建议：{suggestion}"


def _body_drift(drift_info: dict[str, Any] | None) -> str:
    if not drift_info:
        return "Agent 可能偏离了原任务\n风险：中\n建议：收窄任务或回电脑查看"
    task_name = drift_info.get("task_name", "未命名任务")
    violations = drift_info.get("matched_boundary_violations", [])
    v_str = ", ".join(violations[:3])
    return (
        f"原任务：{task_name}；当前行为触碰 {v_str}\n"
        f"风险：中\n"
        f"建议：收窄任务或回电脑查看"
    )


def _body_permission_denied(parsed: dict[str, Any] | None) -> str:
    """Build body for permission_denied — user explicitly denied the operation."""
    raw = parsed or {}
    raw_event = raw.get("raw_event", {}) or {}
    tool_name = raw.get("tool_name", "") or raw_event.get("tool_name", "")
    summary = f"用户已拒绝本次 Agent 操作"
    if tool_name:
        summary += f"（{tool_name}）"
    return f"{summary}\n风险：低\n建议：已记录，无需操作"


def _body_failure(failure_info: dict[str, Any] | None) -> str:
    if not failure_info:
        return "Agent 连续操作失败\n风险：中\n建议：回电脑检查状态"
    count = failure_info.get("consecutive_failures", "?")
    suggestion = failure_info.get("suggestion", "回电脑检查状态")
    return f"Agent 已连续失败 {count} 次\n风险：中\n建议：{suggestion}"
