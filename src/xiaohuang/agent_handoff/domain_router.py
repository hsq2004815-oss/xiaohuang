"""Rule-based database domain routing for Agent Handoff drafts."""

from __future__ import annotations

_DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("xiaohuang_project", ("小黄", "xiaohuang", "控制面板", "任务历史", "语音助手")),
    ("ui_design", ("ui", "页面", "界面", "前端", "玻璃", "美化", "hero", "dashboard")),
    ("backend", ("后端", "api", "fastapi", "数据库", "服务", "registry")),
    ("agent_workflow", ("claude code", "claude", "codex", "opencode", "openclaw", "agent", "提示词", "handoff")),
    ("database", ("数据库", "e:\\database", "brief", "知识库")),
    ("browser_automation", ("浏览器", "自动化", "browser-use", "playwright")),
    ("voice_assistant", ("语音", "唤醒", "asr", "对话")),
)

_DEFAULT_DOMAINS = ("agent_workflow", "xiaohuang_project")


def route_domains(user_request: str) -> list[str]:
    normalized = _normalize(user_request)
    domains: list[str] = []
    for domain, terms in _DOMAIN_RULES:
        if any(_normalize(term) in normalized for term in terms):
            domains.append(domain)
    return domains or list(_DEFAULT_DOMAINS)


def _normalize(text: str) -> str:
    return "".join(str(text or "").lower().split())
