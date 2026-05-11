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

_PROJECT_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s，。；;、]+")

_UNRELATED_XIAOHUANG_TERMS = (
    "和小黄无关",
    "跟小黄无关",
    "不是小黄项目",
    "不要修改小黄",
    "不要改小黄项目",
    "不要修改e:\\projects\\xiaohuang",
    "不要修改e:/projects/xiaohuang",
    "不修改e:\\projects\\xiaohuang",
    "不修改e:/projects/xiaohuang",
    "这个任务和小黄项目无关",
)

_XIAOHUANG_PROJECT_TERMS = (
    "小黄",
    "xiaohuang",
    "控制面板",
    "任务历史",
    "语音助手",
    "agenthandoffcopyux",
    "healthreport",
    "runtimeevents",
    "voiceoverlay",
    "唤醒",
)

_EXTERNAL_PROJECT_TERMS = (
    "前端",
    "页面",
    "界面",
    "官网",
    "react",
    "tailwind",
    "dashboard",
    "saas",
    "品牌",
    "hero",
    "产品展示",
    "玻璃",
    "高级",
    "简历网站",
    "后台管理",
)

_EXTERNAL_NEW_TERMS = (
    "新建一个项目",
    "创建一个项目",
    "从零做一个",
    "做一个新的",
    "新项目",
    "项目放在",
    "做一个",
)

_EXTERNAL_EXISTING_TERMS = (
    "已有项目",
    "现有项目",
    "在项目里",
    "修改项目",
    "优化已有项目",
    "优化现有项目",
)


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

    actual_task = extract_actual_task(original, target_agent=target_agent)
    target_project_path = extract_target_project_path(original)
    project_relation = detect_project_relation(original, actual_task=actual_task)
    target_project_kind = detect_target_project_kind(
        original,
        actual_task,
        target_project_path,
        project_relation=project_relation,
    )

    return AgentHandoffRequest(
        user_request=original,
        target_agent=target_agent,
        actual_task=actual_task,
        project_hint=target_project_path,
        target_project_path=target_project_path,
        target_project_kind=target_project_kind,
        project_relation=project_relation,
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


def extract_target_project_path(text: str) -> str | None:
    match = _PROJECT_PATH_RE.search(str(text or ""))
    if not match:
        return None
    return match.group(0).strip(" ，。；;、")


def detect_project_relation(text: str, actual_task: str = "") -> str:
    combined = _normalize(f"{text} {actual_task}")
    if _contains_any(combined, _UNRELATED_XIAOHUANG_TERMS):
        return "unrelated_to_xiaohuang"
    if _contains_any(combined, _XIAOHUANG_PROJECT_TERMS):
        return "xiaohuang_project"
    return "auto"


def detect_target_project_kind(
    text: str,
    actual_task: str,
    target_project_path: str | None,
    *,
    project_relation: str | None = None,
) -> str:
    relation = project_relation or detect_project_relation(text, actual_task)
    path = str(target_project_path or "")
    if relation == "xiaohuang_project" or _is_xiaohuang_path(path):
        return "xiaohuang"

    combined = _normalize(f"{text} {actual_task}")
    has_external_hint = _contains_any(combined, _EXTERNAL_PROJECT_TERMS)
    if target_project_path:
        if _contains_any(combined, _EXTERNAL_NEW_TERMS) and has_external_hint:
            return "external_new"
        if _contains_any(combined, _EXTERNAL_EXISTING_TERMS):
            return "external_existing"
        return "external_existing"
    if has_external_hint:
        return "external_unspecified"
    return "auto"


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
    value = re.sub(r"^(?:根据我的数据库|根据数据库)[，,、\s]*", "", value)
    value = re.sub(r"在\s*[A-Za-z]:[\\/][^\s，。；;、]+\s*(?:里|中)?[，,、\s]*", "", value)
    value = re.sub(r"项目放在\s*[A-Za-z]:[\\/][^\s，。；;、]+[，,、\s]*", "", value)
    value = re.sub(r"(?:这个任务)?(?:和|跟)小黄项目?无关[，,。；;\s]*", "", value)
    value = re.sub(r"不是小黄项目[，,。；;\s]*", "", value)
    value = re.sub(r"不要(?:修改|改)\s*(?:小黄项目|小黄|[A-Za-z]:[\\/][^\s，。；;、]+)[，,。；;\s]*", "", value)
    for prefix in ("帮我", "去", "来", "继续帮我"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip(" ，。；;：:")
    if value.startswith("看看") and "语音交互" in value and "优化" in value:
        return "分析并优化小黄语音交互方案"
    if value.startswith("看看") and "还能怎么优化" in value:
        value = value.replace("看看", "分析并优化", 1).replace("还能怎么优化", "方案")
    return value or ""


def _is_xiaohuang_path(path: str) -> bool:
    normalized = str(path or "").replace("/", "\\").rstrip("\\").lower()
    return normalized.endswith("\\projects\\xiaohuang")
