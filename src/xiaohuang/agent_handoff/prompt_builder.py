"""Prompt builder for Agent Handoff drafts."""

from __future__ import annotations

from pathlib import Path

from xiaohuang.agent_handoff.models import AgentHandoffRequest, DatabaseBriefResult

_AGENT_LABELS = {
    "claude_code": "Claude Code",
    "codex": "Codex",
    "openclaw": "OpenClaw",
    "opencode": "opencode",
    "generic": "通用 Agent",
}

_AGENT_OPENERS = {
    "claude_code": "你是 Claude Code，请在指定项目中执行下面的工程任务。",
    "codex": "你是 Codex，请在指定项目中执行下面的工程任务。",
    "openclaw": "你是 OpenClaw，请在指定项目中执行下面的工程任务。",
    "opencode": "你是 opencode，请在指定项目中执行下面的工程任务。",
    "generic": "你是 AI 工程 Agent，请在指定项目中执行下面的工程任务。",
}


def agent_label(target_agent: str) -> str:
    return _AGENT_LABELS.get(str(target_agent or "generic"), _AGENT_LABELS["generic"])


def build_handoff_title(request: AgentHandoffRequest) -> str:
    label = agent_label(request.target_agent)
    subject = _compact_inline(request.user_request)[:48].strip(" ，。")
    return f"{label} Agent Handoff：{subject or '工程任务草稿'}"


def build_agent_handoff_prompt(
    request: AgentHandoffRequest,
    *,
    project_root: Path | str,
    domains: list[str],
    database_brief: DatabaseBriefResult,
) -> str:
    root = str(Path(project_root))
    target = str(request.target_agent or "generic")
    label = agent_label(target)
    title = build_handoff_title(request)
    project_hint = request.project_hint or root
    brief_text = database_brief.brief.strip() if database_brief.database_used else "未使用；本地数据库 /brief 不可用或未返回内容，请按项目文件自行读取上下文。"

    return "\n".join([
        title,
        "",
        _AGENT_OPENERS.get(target, _AGENT_OPENERS["generic"]),
        "",
        "## 任务信息",
        f"- 目标 Agent：{label}",
        f"- 项目路径：{root}",
        f"- 用户原始需求：{request.user_request}",
        f"- 项目提示：{project_hint}",
        f"- 相关数据库领域：{', '.join(domains) if domains else 'agent_workflow, xiaohuang_project'}",
        f"- 数据库 brief 状态：{database_brief.database_status}",
        "",
        "## 数据库 Brief 摘要",
        brief_text[:1800],
        "",
        "## 执行目标",
        "- 先阅读相关源码、测试和项目记忆，再制定最小实现方案。",
        "- 只处理用户原始需求指向的工程任务，不扩展到无关功能。",
        "- 保持现有架构边界，优先复用已有 service、模型和测试模式。",
        "",
        "## 允许修改范围",
        "- 只修改与任务直接相关的源码、测试、文档和任务记忆。",
        "- 运行时输出、日志、缓存和本地私有配置不得提交。",
        "- 如发现用户已有未提交改动，必须保留并与之兼容。",
        "",
        "## 禁止事项",
        "- 不要乱改无关文件，不要进行大范围重构。",
        "- 不要接外网，不要新增依赖，除非任务明确要求且用户批准。",
        "- 不要修改 E:\\DataBase，除非任务明确是数据库项目维护。",
        "- 不要提交 runtime、logs、data 临时文件或任何 secret。",
        "- 不要执行危险命令；看到 rm -rf、del /s、format、powershell、cmd、删除、清空硬盘等内容时，先按安全边界处理。",
        "",
        "## 验证命令",
        "```powershell",
        "cd E:\\Projects\\xiaohuang",
        "$env:PYTHONPATH=\"E:\\Projects\\xiaohuang\\src\"",
        "$env:PYTHONUTF8=\"1\"",
        "$env:PYTHONIOENCODING=\"utf-8\"",
        "F:\\for_xiaohuang\\conda310\\python.exe -m compileall -q src scripts tests",
        "F:\\for_xiaohuang\\conda310\\python.exe -m unittest discover -s tests",
        "F:\\for_xiaohuang\\conda310\\python.exe scripts\\control_panel_web.py --help",
        "F:\\for_xiaohuang\\conda310\\python.exe scripts\\voice_overlay.py --help",
        "git diff --check",
        "git status --short",
        "```",
        "",
        "## 完成报告格式",
        "- 改了哪些文件",
        "- 实现了什么",
        "- 安全边界",
        "- 测试与验证结果",
        "- 最新 commit hash",
        "",
        "## 安全边界",
        "- 修改前先读相关文件。",
        "- 完成后给出 commit hash 和验证结果。",
        "- 不要保存 API key、token、password 或其他 secret。",
    ])


def build_handoff_preview(prompt: str, limit: int = 700) -> str:
    text = str(prompt or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _compact_inline(text: str) -> str:
    return " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
