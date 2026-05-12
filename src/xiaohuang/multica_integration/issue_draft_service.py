"""Build safe Multica issue drafts from XiaoHuang Agent Handoff output."""

from __future__ import annotations

import re

from xiaohuang.agent_handoff.intent_parser import normalize_windows_paths_in_text, normalize_windows_target_path
from xiaohuang.multica_integration.models import MulticaIssueDraft

SUGGESTED_ASSIGNEES = ("claude", "codex", "opencode", "openclaw")
_DEFAULT_ASSIGNEE = "claude"
_MAX_TITLE_CHARS = 80
_MAX_COMMAND_DESCRIPTION_CHARS = 1200
_VAGUE_TASK_WARNING = "任务描述过于泛，建议在创建 Multica issue 前补充具体需求。"
_VAGUE_TASK_MARKDOWN_NOTE = "This draft may be too vague for agent execution. Add concrete acceptance criteria before creating a real Multica issue."
_VAGUE_TASK_TERMS = (
    "实现用户请求的功能",
    "完成用户请求",
    "按用户要求修改",
    "处理这个任务",
    "执行任务",
    "做一下这个",
    "requested task",
    "requested changes",
)

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|apikey|token|password|secret)\b\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\b(authorization)\b\s*[:=]\s*(bearer\s+)?([^\r\n,;]+)"),
    re.compile(r"(?i)\bbearer\s+([^\s,;]+)"),
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{8,}\b"),
)


def build_issue_draft_from_handoff(
    *,
    handoff_title: str,
    handoff_prompt: str,
    target_project_path: str,
    target_project_kind: str,
    project_relation: str,
    database_brief_status: str = "",
    related_domains: tuple[str, ...] = (),
    preferred_agent: str = "",
) -> MulticaIssueDraft:
    prompt = normalize_windows_paths_in_text(redact_sensitive_text(handoff_prompt)).strip()
    if not prompt:
        return MulticaIssueDraft(
            ok=False,
            error_code="missing_handoff_prompt",
            message="缺少 Agent Handoff prompt，无法生成 Multica issue 草稿。",
        )

    target_path = normalize_windows_target_path(redact_sensitive_text(target_project_path))
    title_source = normalize_windows_paths_in_text(redact_sensitive_text(handoff_title or _extract_prompt_title(prompt) or "Agent Handoff"))
    title = _build_issue_title(title_source, target_path)
    default_assignee = _select_default_assignee(preferred_agent, title_source + "\n" + prompt)
    relation = _compact_inline(project_relation or "unknown")
    kind = _compact_inline(target_project_kind or "auto")
    domains = tuple(_compact_inline(item) for item in related_domains if _compact_inline(item))
    warnings = [
        "仅草稿，未创建 Multica issue，未分配 Agent。",
        "复制后由用户手动执行；小黄不会自动运行 multica issue create。",
    ]
    if not target_path:
        warnings.append("目标项目路径为空；创建 issue 前请先确认 target_project_path。")
    is_vague = _is_vague_task_text(title_source + "\n" + prompt)
    if is_vague:
        warnings.append(_VAGUE_TASK_WARNING)

    description = _build_description(
        title=title,
        handoff_prompt=prompt,
        target_project_path=target_path,
        target_project_kind=kind,
        project_relation=relation,
        database_brief_status=_compact_inline(database_brief_status or "unknown"),
        related_domains=domains,
        vague_task=is_vague,
    )
    command_preview = _build_command_preview(
        title=title,
        description=description,
        warnings=warnings,
    )
    markdown = _build_markdown(
        title=title,
        default_assignee=default_assignee,
        target_project_path=target_path,
        target_project_kind=kind,
        project_relation=relation,
        command_preview=command_preview,
        description=description,
        warnings=warnings,
        vague_task=is_vague,
    )
    return MulticaIssueDraft(
        ok=True,
        title=title,
        description=description,
        target_project_path=target_path,
        project_relation=relation,
        suggested_assignees=SUGGESTED_ASSIGNEES,
        default_assignee=default_assignee,
        create_command_preview=command_preview,
        markdown=markdown,
        warnings=tuple(warnings),
        message="Multica issue 草稿已生成；未创建 issue，未分配 Agent。",
    )


def redact_sensitive_text(text: str) -> str:
    value = str(text or "")
    value = _SENSITIVE_PATTERNS[0].sub(r"\g<1>=<redacted>", value)
    value = _SENSITIVE_PATTERNS[1].sub(r"\g<1>=<redacted>", value)
    value = _SENSITIVE_PATTERNS[2].sub("Bearer <redacted>", value)
    value = _SENSITIVE_PATTERNS[3].sub("sk-<redacted>", value)
    return value


def _build_issue_title(title_source: str, target_project_path: str) -> str:
    title = _compact_inline(title_source)
    title = re.sub(r"(?i)\b(agent handoff|claude code|codex|openclaw|opencode|通用 agent)\b[:：-]*", "", title).strip()
    if not title:
        title = "Multica issue draft"
    target_name = _target_name(target_project_path)
    if target_name and target_name.lower() not in title.lower() and len(title) < 54:
        title = f"{title} ({target_name})"
    title = title.replace("\n", " ").replace("\r", " ")
    title = " ".join(title.split())
    if len(title) > _MAX_TITLE_CHARS:
        title = title[:_MAX_TITLE_CHARS].rstrip(" ，。,:：-") + "..."
    return title or "Multica issue draft"


def _build_description(
    *,
    title: str,
    handoff_prompt: str,
    target_project_path: str,
    target_project_kind: str,
    project_relation: str,
    database_brief_status: str,
    related_domains: tuple[str, ...],
    vague_task: bool,
) -> str:
    lines = [
        "# XiaoHuang Agent Handoff",
        "",
        "## Task",
        title,
    ]
    if vague_task:
        lines.extend([
            "",
            "## Draft Quality Warning",
            _VAGUE_TASK_MARKDOWN_NOTE,
        ])
    lines.extend([
        "",
        "## Target Project",
        f"- Path: {target_project_path or '未指定'}",
        f"- Kind: {target_project_kind or 'auto'}",
        f"- Relation: {project_relation or 'unknown'}",
        "",
        "## Database Context",
        f"- Brief status: {database_brief_status or 'unknown'}",
        f"- Related domains: {', '.join(related_domains) if related_domains else '未指定'}",
        "",
        "## Execution Instructions",
        handoff_prompt,
        "",
        "## Safety Boundaries",
        "- Do not modify E:\\DataBase.",
        "- Do not modify E:\\Projects\\xiaohuang unless this is explicitly a xiaohuang project task.",
        "- Do not run destructive commands.",
        "- Follow the target project path.",
        "- Preserve existing user changes.",
        "- Do not save API keys, tokens, passwords, or secrets.",
    ])
    return "\n".join(lines)


def _build_command_preview(
    *,
    title: str,
    description: str,
    warnings: list[str],
) -> str:
    description_arg = description
    if len(description_arg) > _MAX_COMMAND_DESCRIPTION_CHARS:
        description_arg = "<description too long; copy Issue 描述或 Markdown 草稿>"
        warnings.append("description 较长，命令草稿使用占位描述；建议复制 Issue 描述或下载 Markdown 草稿。")
    return " ".join([
        "multica issue create",
        "--title", _ps_quote(title),
        "--description", _ps_quote(description_arg),
        "--output json",
    ])


def _build_markdown(
    *,
    title: str,
    default_assignee: str,
    target_project_path: str,
    target_project_kind: str,
    project_relation: str,
    command_preview: str,
    description: str,
    warnings: list[str],
    vague_task: bool,
) -> str:
    lines = [
        "# Multica Issue Draft",
        "",
        "## Title",
        title,
        "",
        "## Suggested Assignee",
        default_assignee,
        "",
        "## Target Project",
        f"- Path: {target_project_path or '未指定'}",
        f"- Kind: {target_project_kind or 'auto'}",
        f"- Relation: {project_relation or 'unknown'}",
        "",
        "## Create Command Preview",
        "```powershell",
        command_preview,
        "```",
        "",
        "## Description",
        description,
        "",
    ]
    if vague_task:
        lines.extend([
            "## Draft Quality Warning",
            _VAGUE_TASK_MARKDOWN_NOTE,
            "",
        ])
    lines.extend([
        "## Safety Notes",
        *[f"- {item}" for item in warnings],
        "",
    ])
    return "\n".join(lines)


def _select_default_assignee(preferred_agent: str, text: str) -> str:
    preferred = _normalize_agent(preferred_agent)
    if preferred in SUGGESTED_ASSIGNEES:
        return preferred
    lower = str(text or "").lower()
    if "codex" in lower:
        return "codex"
    if "claude" in lower:
        return "claude"
    return _DEFAULT_ASSIGNEE


def _normalize_agent(value: str) -> str:
    text = _compact_inline(value).lower()
    if text in {"claude", "claude_code", "claude code"}:
        return "claude"
    if text in {"codex"}:
        return "codex"
    if text in {"opencode", "open code"}:
        return "opencode"
    if text in {"openclaw", "open claw"}:
        return "openclaw"
    return text


def _ps_quote(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _extract_prompt_title(prompt: str) -> str:
    for line in str(prompt or "").splitlines():
        value = line.strip().lstrip("#").strip()
        if value:
            return value
    return ""


def _target_name(path: str) -> str:
    value = normalize_windows_target_path(path).rstrip("\\/")
    if not value:
        return ""
    return re.split(r"[\\/]", value)[-1].strip()


def _compact_inline(text: str) -> str:
    return " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())


def _is_vague_task_text(text: str) -> bool:
    normalized = _compact_inline(text).lower()
    return any(term.lower() in normalized for term in _VAGUE_TASK_TERMS)
