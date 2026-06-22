"""Persona themes — notification title & body overrides for each event type.

All persona texts are original.  No quotes from copyrighted works.
"""

from __future__ import annotations

from typing import Any

# ── Theme names (config value → display name) ───────────────────────────

THEME_NAMES: dict[str, str] = {
    "off":         "Off",
    "boss":        "总裁版",
    "heir_male":   "少爷版",
    "heir_female": "大小姐版",
    "emperor":     "皇上版",
    "palace":      "甄嬛版",
}

# Order for menu display.
THEME_ORDER = ["off", "boss", "heir_male", "heir_female", "emperor", "palace"]

# ── Persona templates ───────────────────────────────────────────────────
#
# Each theme is a dict mapping event_type → {"title": ..., "body": ...}.
# If an event_type is missing, the default (non-persona) message is used.

PERSONAS: dict[str, dict[str, dict[str, str]]] = {
    # ── boss — 总裁版（发疯爽剧抓马风）────────────────────────────────
    "boss": {
        "permission_required": {
            "title": "总裁快签字",
            "body": "总裁！没有您的签字，整个项目组一步都不敢往前走！\n建议：回电脑点击 Allow。",
        },
        "task_done": {
            "title": "项目拿下了",
            "body": "总裁！项目成了！这一局，轮到我们赢了！\n建议：回电脑验收成果。",
        },
        "task_done_pending_bg": {
            "title": "主力收工，后方还在干",
            "body": "总裁！台面上的活儿收了，可后台还有一队人在加班跑流程，这会儿别急着庆功。\n建议：等后台那摊跑完再验收。",
        },
        "attention_required": {
            "title": "全场等您一句话",
            "body": "总裁，现在所有人都在等您拍板。\n建议：回电脑处理。",
        },
        "danger": {
            "title": "有人动了保险柜",
            "body": "总裁！有人碰了不该碰的东西，这一步不能让他们自己决定！\n建议：立即回电脑确认。",
        },
        "drift": {
            "title": "他们开始不听话了",
            "body": "总裁！项目组已经偏离原定方向，再不管就要收购隔壁公司了！\n建议：收窄任务范围。",
        },
        "failure": {
            "title": "他们又撞墙了",
            "body": "总裁！项目组连续失败，再这样下去今晚全员加班！\n建议：回电脑查看阻塞原因。",
        },
        "info": {
            "title": "暂时稳住了",
            "body": "总裁，局面暂时还在掌控之中，您可以继续摸鱼。",
        },
        "possible_permission_wait": {
            "title": "会议室还亮着",
            "body": "总裁，项目组那边还没回信，可能在等您，也可能还在加班。\n建议：有空回电脑看一眼。",
        },
        "permission_denied": {
            "title": "文件被驳回",
            "body": "总裁已驳回这份文件，项目组不敢继续推进。",
        },
    },

    # ── heir_male — 少爷版 ──────────────────────────────────────────────
    "heir_male": {
        "permission_required": {
            "title": "待您过目",
            "body": "少爷，这一步管家不敢擅自处理，还请您亲自点头。\n建议：回电脑点击 Allow。",
        },
        "task_done": {
            "title": "事情办妥了",
            "body": "少爷，您吩咐的事已经办妥，请您验收。",
        },
        "task_done_pending_bg": {
            "title": "主事办完，杂务未了",
            "body": "少爷，明面上的事办妥了，可后头还有几桩杂务在办，暂未全清。\n建议：稍候，等后头办完再验收。",
        },
        "attention_required": {
            "title": "请您定夺",
            "body": "少爷，下面的人拿不准主意，还请您回电脑定夺。",
        },
        "danger": {
            "title": "保险柜被打开了",
            "body": "少爷，有人碰了不该碰的东西，建议您立刻回电脑。",
        },
        "drift": {
            "title": "下属自作主张",
            "body": "少爷，下面的人开始擅自扩张版图，建议您敲打一下。",
        },
        "failure": {
            "title": "下面的人办不动了",
            "body": "少爷，项目组在原地打转，需要您亲自看一眼。",
        },
        "info": {
            "title": "下人正在办",
            "body": "少爷，事情还在稳步推进，暂时无需您出面。",
        },
        "possible_permission_wait": {
            "title": "事情还悬着",
            "body": "少爷，这一步还没回音，可能在等您点头，也可能下面的人还在办。",
        },
        "permission_denied": {
            "title": "已被驳回",
            "body": "少爷没有点头，下面的人不敢再办。",
        },
    },

    # ── heir_female — 大小姐版 ──────────────────────────────────────────
    "heir_female": {
        "permission_required": {
            "title": "待您过目",
            "body": "大小姐，这一步管家不敢擅自处理，还请您亲自点头。\n建议：回电脑点击 Allow。",
        },
        "task_done": {
            "title": "事情办妥了",
            "body": "大小姐，您吩咐的事已经办妥，请您验收。",
        },
        "task_done_pending_bg": {
            "title": "主事办完，杂务未了",
            "body": "大小姐，明面上的事办妥了，可后头还有几桩杂务在办，暂未全清。\n建议：稍候，等后头办完再验收。",
        },
        "attention_required": {
            "title": "请您定夺",
            "body": "大小姐，下面的人拿不准主意，还请您回电脑定夺。",
        },
        "danger": {
            "title": "保险柜被打开了",
            "body": "大小姐，有人碰了不该碰的东西，建议您立刻回电脑。",
        },
        "drift": {
            "title": "下属自作主张",
            "body": "大小姐，下面的人开始擅自扩张版图，建议您敲打一下。",
        },
        "failure": {
            "title": "下面的人办不动了",
            "body": "大小姐，项目组在原地打转，需要您亲自看一眼。",
        },
        "info": {
            "title": "下人正在办",
            "body": "大小姐，事情还在稳步推进，暂时无需您出面。",
        },
        "possible_permission_wait": {
            "title": "事情还悬着",
            "body": "大小姐，这一步还没回音，可能在等您点头，也可能下面的人还在办。",
        },
        "permission_denied": {
            "title": "已被驳回",
            "body": "大小姐没有点头，下面的人不敢再办。",
        },
    },

    # ── emperor — 皇上版（太监请示+京腔）───────────────────────────────
    "emperor": {
        "permission_required": {
            "title": "奏请御批",
            "body": "皇上，奴才这儿有道折子，非您御批不可。\n请回电脑点击 Allow。",
        },
        "task_done": {
            "title": "差事办妥",
            "body": "皇上，差事已经办妥，就等您御览。",
        },
        "task_done_pending_bg": {
            "title": "主差办妥，余事未了",
            "body": "皇上，主差是办妥了，可还有几桩杂事，奴才们仍在后头忙活。\n请您稍候御览。",
        },
        "attention_required": {
            "title": "请皇上定夺",
            "body": "皇上，下面的人拿不准主意，特来请您圣裁。",
        },
        "danger": {
            "title": "触犯禁区",
            "body": "皇上，不好了，有人动了宫里的禁物，请您速速御览。",
        },
        "drift": {
            "title": "办差走偏",
            "body": "皇上，这差事办着办着，方向似乎偏了。",
        },
        "failure": {
            "title": "奴才办不动了",
            "body": "皇上，下面的人连番受阻，怕是得您亲自过问。",
        },
        "info": {
            "title": "正在办差",
            "body": "皇上放心，奴才们还在办差，暂不用您操心。",
        },
        "possible_permission_wait": {
            "title": "疑似候旨",
            "body": "皇上，这道折子还悬着，许是在等旨，也许奴才们还在办。\n建议：得空回电脑瞧一眼。",
        },
        "permission_denied": {
            "title": "御批驳回",
            "body": "皇上已驳回这道折子，奴才们不敢再办。",
        },
    },

    # ── palace — 甄嬛版 / 宫斗版（原创后宫内务风）─────────────────────
    "palace": {
        "permission_required": {
            "title": "请主子示下",
            "body": "主子，这一步内务府不敢擅自做主，还请您回电脑示下。",
        },
        "task_done": {
            "title": "差事已成",
            "body": "主子吩咐的差事已经办妥，现呈上请您过目。",
        },
        "task_done_pending_bg": {
            "title": "主事已成，余事未了",
            "body": "主子，主事虽已办妥，可还有几桩首尾，奴才们仍在后头打点。\n还请主子稍候过目。",
        },
        "attention_required": {
            "title": "请主子定夺",
            "body": "主子，此事关系后续安排，还需您亲自定夺。",
        },
        "danger": {
            "title": "宫中有异动",
            "body": "主子，有人碰了不该碰的东西，此事不宜拖延。",
        },
        "drift": {
            "title": "办事失了分寸",
            "body": "主子，下面的人办事有些失了分寸，恐怕得您敲打。",
        },
        "failure": {
            "title": "差事受阻",
            "body": "主子，这差事连番受阻，奴才们有些撑不住了。",
        },
        "info": {
            "title": "暂且安稳",
            "body": "主子放心，眼下宫里还算安稳，暂不劳您费心。",
        },
        "possible_permission_wait": {
            "title": "事情未落定",
            "body": "主子，这一步尚未有回音，许是在等您示下，也许还在办着。",
        },
        "permission_denied": {
            "title": "示下已回",
            "body": "主子没有准这一步，内务府不敢再动。",
        },
    },
}


# ── Public API ──────────────────────────────────────────────────────────


def get_persona_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return the persona config dict, with defaults."""
    p = config.get("persona", {}) or {}
    p.setdefault("enabled", True)
    p.setdefault("theme", "off")
    p.setdefault("user_role", "")
    return p


def theme_display_name(theme: str) -> str:
    """Human-readable name for a theme key."""
    return THEME_NAMES.get(theme, theme)


def apply_persona(
    event_type: str,
    title: str,
    body: str,
    config: dict[str, Any],
) -> tuple[str, str]:
    """If a persona is enabled, replace *title* and *body* with the theme's version.

    Returns (title, body) — either the persona version or the original.
    """
    pc = get_persona_config(config)
    if not pc.get("enabled", False):
        return title, body

    theme = pc.get("theme", "off")
    if theme == "off":
        return title, body

    templates = PERSONAS.get(theme, {})
    tpl = templates.get(event_type)
    if tpl is None:
        return title, body

    return tpl.get("title", title), tpl.get("body", body)


def valid_themes() -> list[str]:
    """Return all valid theme keys (including 'off')."""
    return list(THEME_NAMES.keys())
