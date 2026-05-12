"""Rule-based database domain routing for Agent Handoff drafts."""

from __future__ import annotations

_DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("xiaohuang_project", ("小黄", "xiaohuang", "控制面板", "任务历史", "语音助手", "agent handoff", "completion review", "runtime events", "voice overlay", "唤醒", "健康检查")),
    ("ui_design", ("ui", "页面", "界面", "前端", "玻璃", "美化", "hero", "dashboard", "官网", "react", "tailwind", "saas", "品牌", "产品展示", "高级")),
    ("backend", ("后端", "api", "fastapi", "服务", "registry")),
    ("agent_workflow", ("claude code", "claude", "codex", "opencode", "openclaw", "agent", "提示词", "handoff")),
    ("database", ("e:\\database", "brief", "知识库")),
    ("browser_automation", ("浏览器", "自动化", "browser-use", "playwright")),
    ("voice_assistant", ("语音", "唤醒", "asr", "对话")),
)

_DEFAULT_DOMAINS = ("agent_workflow",)
_UNRELATED_XIAOHUANG_TERMS = (
    "unrelated_to_xiaohuang",
    "和小黄无关",
    "跟小黄无关",
    "不是小黄项目",
    "不修改小黄",
    "不修改小黄项目",
    "不要修改小黄",
    "不要修改小黄项目",
    "不改小黄",
    "不改小黄项目",
    "不要改小黄",
    "不要改小黄项目",
    "不要修改e:\\projects\\xiaohuang",
    "不要修改e:/projects/xiaohuang",
    "不修改e:\\projects\\xiaohuang",
    "不修改e:/projects/xiaohuang",
)


def route_domains(user_request: str) -> list[str]:
    normalized = _normalize(user_request)
    domains: list[str] = []
    for domain, terms in _DOMAIN_RULES:
        if domain == "xiaohuang_project" and _contains_any(normalized, _UNRELATED_XIAOHUANG_TERMS):
            continue
        if any(_normalize(term) in normalized for term in terms):
            domains.append(domain)
    return domains or list(_DEFAULT_DOMAINS)


def _normalize(text: str) -> str:
    return "".join(str(text or "").lower().split())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_normalize(term) in text for term in terms)
