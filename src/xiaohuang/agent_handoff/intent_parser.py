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


def _extract_project_hint(text: str) -> str | None:
    match = _PROJECT_PATH_RE.search(str(text or ""))
    return match.group(0) if match else None


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_normalize(term) in text for term in terms)


def _normalize(text: str) -> str:
    return "".join(str(text or "").lower().split())
