"""Natural-language intent parsing for Agent Handoff draft tasks."""

from __future__ import annotations

import re

from xiaohuang.agent_handoff.models import AgentHandoffRequest

_TARGET_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude_code", ("claudecode", "claude")),
    ("codex", ("codex",)),
    ("openclaw", ("openclaw",)),
    ("opencode", ("opencode", "open code", "opencode")),
)

_HANDOFF_KEYWORDS = (
    "生成提示词",
    "写提示词",
    "交接提示词",
    "提示词草稿",
    "handoff",
    "agenthandoff",
    "给agent",
    "给aiagent",
    "根据我的数据库生成提示词",
)

_TARGET_ACTION_TERMS = (
    "给",
    "让",
    "生成",
    "写",
    "任务",
    "提示词",
    "继续",
    "优化",
    "审查",
    "review",
    "改",
    "做",
)

_PROJECT_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s，。；;]+")


def parse_agent_handoff_intent(text: str, *, source: str = "text") -> AgentHandoffRequest | None:
    original = str(text or "").strip()
    if not original:
        return None

    normalized = _normalize(original)
    target_agent = detect_target_agent(original)
    has_handoff_keyword = _contains_any(normalized, _HANDOFF_KEYWORDS)
    has_target_action = target_agent != "generic" and _contains_any(normalized, _TARGET_ACTION_TERMS)

    if not has_handoff_keyword and not has_target_action:
        return None

    return AgentHandoffRequest(
        user_request=original,
        target_agent=target_agent,
        actual_task=extract_actual_task(original, target_agent=target_agent),
        project_hint=_extract_project_hint(original),
        domain_hints=[],
        source=str(source or "text"),
        use_database=True,
    )


def detect_target_agent(text: str) -> str:
    normalized = _normalize(text)
    for target, aliases in _TARGET_ALIASES:
        if any(_normalize(alias) in normalized for alias in aliases):
            return target
    return "generic"


def extract_actual_task(text: str, target_agent: str = "generic") -> str:
    original = _strip_wrappers(str(text or "").strip())
    if not original:
        return ""

    lowered = original.lower()
    if "数据库" in original and "提示词" in original and ("ui" in lowered or "页面" in original or "界面" in original):
        return "生成高级 UI 页面开发方案，并根据数据库规则执行页面开发任务"

    for marker in ("让它", "让他", "让其"):
        idx = original.find(marker)
        if idx >= 0:
            return _polish_actual_task(original[idx + len(marker):])

    agent_names = _agent_name_patterns(target_agent)
    for name in agent_names:
        for prefix in (f"让{name}", f"让 {name}"):
            idx = original.lower().find(prefix.lower())
            if idx >= 0:
                tail = original[idx + len(prefix):]
                return _polish_actual_task(tail)

    for verb in ("继续", "修复", "优化", "审查", "实现", "设计"):
        idx = original.find(verb)
        if idx >= 0:
            return _polish_actual_task(original[idx:])

    return _polish_actual_task(original)


def _extract_project_hint(text: str) -> str | None:
    match = _PROJECT_PATH_RE.search(str(text or ""))
    return match.group(0) if match else None


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_normalize(term) in text for term in terms)


def _normalize(text: str) -> str:
    return "".join(str(text or "").lower().split())


def _strip_wrappers(text: str) -> str:
    value = str(text or "").strip(" ，。；;")
    for prefix in ("根据我的数据库", "根据数据库", "帮我", "请帮我", "小黄"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip(" ，。；;")
    return value


def _agent_name_patterns(target_agent: str) -> tuple[str, ...]:
    names = {
        "claude_code": ("Claude Code", "claude code", "Claude", "claude"),
        "codex": ("Codex", "codex"),
        "openclaw": ("OpenClaw", "openclaw"),
        "opencode": ("opencode", "OpenCode", "open code"),
        "generic": ("agent", "Agent", "AI Agent"),
    }
    return names.get(str(target_agent or "generic"), names["generic"])


def _polish_actual_task(text: str) -> str:
    value = str(text or "").strip(" ，。；;：:")
    for prefix in ("帮我", "去", "来", "继续帮我"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip(" ，。；;：:")
    if value.startswith("看看") and "语音交互" in value and "优化" in value:
        return "分析并优化小黄语音交互方案"
    if value.startswith("看看") and "还能怎么优化" in value:
        value = value.replace("看看", "分析并优化", 1).replace("还能怎么优化", "方案")
    return value or ""
