"""readonly_tools.py — C5H-B readonly tool implementations.

Four readonly tools with strict path safety and output limits.
Aligned with claw-code's tool execution pattern: tools receive structured input,
return output text, errors are caught and returned as tool results.

Path safety is the primary security concern — all file operations go through
resolve_project_path and is_path_allowed before any IO.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from xiaohuang.tool_runtime.tool_types import ToolSpec, RISK_READONLY

# ---------------------------------------------------------------------------
# Default project root — may be overridden via env/config
# ---------------------------------------------------------------------------

_DEFAULT_PROJECT_ROOT = Path(r"E:\Projects\xiaohuang")
_DISALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".env", ".sqlite", ".db", ".sqlite3", ".db3",
    ".pem", ".p12", ".pfx", ".key", ".keystore",
})
_DISALLOWED_FILENAME_PATTERNS: tuple[str, ...] = (
    ".env", "secrets.ps1", "secret", "secrets", "key",
    "token", "credential", "credentials", "api_key",
)
_DISALLOWED_DIR_NAMES: frozenset[str] = frozenset({
    ".git", ".venv", "__pycache__", "node_modules",
    "runtime", ".claude", "models", "logs", "data",
})
_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".css", ".html", ".md", ".txt",
    ".json", ".yaml", ".yml", ".toml", ".ps1",
})
_MAX_OUTPUT_CHARS_DEFAULT = 6000
_UNC_PATTERN = re.compile(r"^\\\\[^?]")
_WINDOWS_DRIVE_PATTERN = re.compile(r"^[a-zA-Z]:[/\\]")


def _default_project_root() -> Path:
    env_root = os.environ.get("XIAOHUANG_PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return _DEFAULT_PROJECT_ROOT


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def resolve_project_path(
    relative_path: str, *, project_root: Path | None = None
) -> Path:
    """Resolve a relative path safely within the project root.

    Rejects absolute paths, UNC paths, Windows drive-letter paths,
    and path traversal attempts.
    """
    root = project_root or _default_project_root()
    root = root.resolve()
    raw = str(relative_path or "").strip()

    if not raw:
        raise ValueError("path is empty")

    if os.path.isabs(raw):
        raise ValueError(f"absolute path not allowed: {raw!r}")

    if _UNC_PATTERN.match(raw):
        raise ValueError(f"UNC path not allowed: {raw!r}")

    if _WINDOWS_DRIVE_PATTERN.match(raw):
        raise ValueError(f"drive-letter path not allowed: {raw!r}")

    candidate = (root / raw).resolve()

    # Ensure the resolved path stays under project root
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(f"path traversal detected: {raw!r} -> {str(candidate)!r}")

    return candidate


def is_path_allowed(path: Path, *, project_root: Path | None = None) -> bool:
    """Check if a path is within project root and not sensitive."""
    root = project_root or _default_project_root()
    root = root.resolve()
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return not is_sensitive_path(path)


def is_sensitive_path(path: Path) -> bool:
    """Check if a path points to sensitive content.

    Checks: directory names, filename patterns, extensions.
    """
    resolved = path.resolve()
    parts = resolved.parts
    for part in parts:
        if part in _DISALLOWED_DIR_NAMES:
            return True

    filename = resolved.name.lower()
    for pattern in _DISALLOWED_FILENAME_PATTERNS:
        if pattern in filename:
            return True

    if resolved.suffix.lower() in _DISALLOWED_EXTENSIONS:
        return True

    return False


def is_allowed_text_file(path: Path) -> bool:
    """Check if a file has an allowed extension for reading."""
    suffix = path.suffix.lower()
    # .ps1 files with 'secret' in name are disallowed
    if suffix == ".ps1" and "secret" in path.name.lower():
        return False
    return suffix in _ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _truncate_output(output: str, max_chars: int) -> tuple[str, bool]:
    if len(output) <= max_chars:
        return output, False
    truncated = output[:max_chars] + f"\n\n[已截断，原文共 {len(output)} 字符]"
    return truncated, True


def _safe_read_text(path: Path, max_chars: int) -> tuple[str, bool]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"读取文件失败: {exc}", False
    return _truncate_output(text, max_chars)


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


def get_current_conversation_context(
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> str:
    """Return the current conversation's ContextPack summary.

    Only reads the current conversation_id — cannot read other conversations.
    """
    ctx = context or {}
    conversation_id = ctx.get("conversation_id", "")
    lines = [f"当前会话 ID: {conversation_id}"]

    goal = ctx.get("current_goal", "")
    status = ctx.get("current_status", "")
    next_step = ctx.get("next_step", "")
    constraints = ctx.get("important_constraints", [])
    compact_summary = ctx.get("compact_summary", "")

    if goal:
        lines.append(f"当前目标: {goal}")
    if status:
        lines.append(f"当前状态: {status}")
    if next_step:
        lines.append(f"下一步: {next_step}")
    if constraints:
        lines.append(f"重要约束: {', '.join(constraints)}")
    if compact_summary:
        lines.append(f"历史摘要: {compact_summary}")

    return "\n".join(lines)


def list_project_files_readonly(
    arguments: dict[str, Any],
    *,
    project_root: Path | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    """List files in a project subdirectory.

    Parameters: relative_dir (str), max_results (int, default 50, max 100)
    """
    relative_dir = str(arguments.get("relative_dir", "") or "").strip()
    max_results = min(int(arguments.get("max_results", 50) or 50), 100)
    root = project_root or _default_project_root()

    if not relative_dir:
        relative_dir = "."

    target = resolve_project_path(relative_dir, project_root=root)
    if not is_path_allowed(target, project_root=root):
        raise ValueError("拒绝访问: 目录不在允许范围内")

    if is_sensitive_path(target):
        raise ValueError("拒绝访问: 目录为敏感目录")

    results = []
    try:
        entries = sorted(target.iterdir(), key=lambda p: (p.is_dir(), p.name.lower()))
    except Exception as exc:
        return f"列出目录失败: {exc}"

    for entry in entries:
        if len(results) >= max_results:
            break
        name = entry.name
        # Skip hidden files (except .py and allowed extensions)
        if name.startswith(".") and not name.endswith(tuple(_ALLOWED_EXTENSIONS)):
            continue
        if entry.is_dir():
            if name in _DISALLOWED_DIR_NAMES:
                continue
            results.append(f"[目录] {name}/")
        elif is_allowed_text_file(entry):
            try:
                size = entry.stat().st_size
                results.append(f"[文件] {name} ({_format_size(size)})")
            except Exception:
                results.append(f"[文件] {name}")
        elif entry.is_file():
            # Binary or disallowed extension — show but mark restricted
            try:
                size = entry.stat().st_size
                results.append(f"[受限] {name} ({_format_size(size)})")
            except Exception:
                results.append(f"[受限] {name}")

    info = f"目录: {relative_dir}\n文件数: {len(results)}"
    if len(results) >= max_results:
        info += f" (已达上限 {max_results})"
    return f"{info}\n\n" + "\n".join(results) if results else info + "\n(空目录)"


def read_project_file_readonly(
    arguments: dict[str, Any],
    *,
    project_root: Path | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    """Read the contents of a project file.

    Parameters: path (str), max_chars (int, default 6000, max 6000)
    """
    file_path = str(arguments.get("path", "") or "").strip()
    max_chars = min(int(arguments.get("max_chars", _MAX_OUTPUT_CHARS_DEFAULT) or _MAX_OUTPUT_CHARS_DEFAULT), _MAX_OUTPUT_CHARS_DEFAULT)
    root = project_root or _default_project_root()

    if not file_path:
        raise ValueError("未指定文件路径")

    try:
        resolved = resolve_project_path(file_path, project_root=root)
    except ValueError:
        raise

    if not is_path_allowed(resolved, project_root=root):
        raise ValueError("拒绝访问: 文件不在允许范围内")

    if is_sensitive_path(resolved):
        raise ValueError("拒绝访问: 文件为敏感文件")

    if not is_allowed_text_file(resolved):
        raise ValueError(f"拒绝访问: 不允许读取 .{resolved.suffix.lstrip('.')} 类型文件")

    if not resolved.is_file():
        raise ValueError(f"文件不存在: {file_path}")

    try:
        file_size = resolved.stat().st_size
    except Exception:
        file_size = 0

    if file_size > 500_000:
        raise ValueError(f"文件过大 ({_format_size(file_size)})，超过 500KB 限制")

    text, truncated = _safe_read_text(resolved, max_chars)
    prefix = f"=== {file_path} ({_format_size(file_size)})" + (" [已截断]" if truncated else "") + " ===\n"
    return prefix + text


def search_project_text_readonly(
    arguments: dict[str, Any],
    *,
    project_root: Path | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    """Search for text in project files.

    Parameters: query (str), relative_dir (str, default "."), max_results (int, default 20, max 50)
    """
    query = str(arguments.get("query", "") or "").strip()
    relative_dir = str(arguments.get("relative_dir", "") or "").strip() or "."
    max_results = min(int(arguments.get("max_results", 20) or 20), 50)
    root = project_root or _default_project_root()

    if not query:
        raise ValueError("搜索关键词不能为空")
    if len(query) > 200:
        raise ValueError("搜索关键词过长（上限 200 字符）")

    try:
        target = resolve_project_path(relative_dir, project_root=root)
    except ValueError:
        raise

    if not is_path_allowed(target, project_root=root):
        raise ValueError("拒绝访问: 目录不在允许范围内")

    results = []
    # If query contains backslashes, use literal match
    query_lower = query.lower()
    try:
        search_pattern = re.compile(re.escape(query_lower), re.IGNORECASE)
    except re.error:
        return f"搜索模式错误: {query!r}"

    try:
        for entry in sorted(target.rglob("*")):
            if len(results) >= max_results:
                break
            if not entry.is_file():
                continue
            if is_sensitive_path(entry):
                continue
            if not is_allowed_text_file(entry):
                continue
            try:
                if entry.stat().st_size > 500_000:
                    continue
            except Exception:
                continue
            try:
                content = entry.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            matches = search_pattern.findall(content)  # not used, just presence
            if matches:
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    if len(results) >= max_results:
                        break
                    if query_lower in line.lower():
                        snippet = line.strip()
                        if len(snippet) > 200:
                            snippet = snippet[:200] + "…"
                        rel = entry.relative_to(root) if root in entry.parents else entry
                        results.append(f"{rel}:{i + 1}: {snippet}")
    except Exception as exc:
        return f"搜索失败: {exc}"

    info = f"搜索: '{query}' (目录: {relative_dir})\n匹配: {len(results)} 条"
    if len(results) >= max_results:
        info += f" (已达上限 {max_results})"
    return f"{info}\n\n" + "\n".join(results) if results else info + "\n(未找到匹配)"


# ---------------------------------------------------------------------------
# C5H-C: External readonly knowledge tools
# ---------------------------------------------------------------------------


def get_multica_bound_tasks_readonly(
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> str:
    """Return Multica tasks bound to the current conversation.

    Requires history_store and conversation_id via context dict.
    """
    ctx = context or {}
    conversation_id = str(ctx.get("conversation_id") or "").strip()
    if not conversation_id:
        raise ValueError("缺少 conversation_id，无法查询绑定的 Multica 任务")

    history_store = ctx.get("history_store")
    if history_store is None:
        raise ValueError("history_store 不可用，无法查询 Multica 任务绑定")

    try:
        tasks = history_store.get_bound_tasks(conversation_id)
    except Exception as exc:
        raise ValueError(f"查询 Multica 任务绑定失败: {exc}")

    import json

    task_list = []
    for task in tasks:
        task_list.append({
            "task_id": task.task_id or task.issue_id or task.id,
            "title": task.title or "",
            "status": task.run_status or "",
            "summary": task.review_summary or "",
            "agent": task.agent or "",
            "messages_count": task.messages_count,
            "tool_use_count": task.tool_use_count,
            "tool_result_count": task.tool_result_count,
        })

    result = {
        "conversation_id": conversation_id,
        "tasks": task_list,
        "count": len(task_list),
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def search_database_brief_readonly(
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> str:
    """Query the local database /brief API for knowledge retrieval.

    Uses http://127.0.0.1:8765/brief (readonly).
    Does not read or write E:\DataBase files directly.
    """
    from xiaohuang.agent_handoff import database_brief_client

    query = str(arguments.get("query", "") or "").strip()
    if not query:
        raise ValueError("查询关键词不能为空")
    if len(query) > 500:
        raise ValueError("查询关键词过长（上限 500 字符）")

    domain = str(arguments.get("domain", "") or "").strip()
    domains = [domain] if domain else []

    limit = min(int(arguments.get("limit", 5) or 5), 10)

    try:
        result = database_brief_client.fetch_database_brief(
            query=query,
            domains=domains,
            timeout=5.0,
        )
    except Exception as exc:
        raise ValueError(f"数据库查询失败: {exc}")

    import json

    if result.database_used and result.brief:
        brief = result.brief
        if len(brief) > 3000:
            brief = brief[:3000] + "\n\n[输出已截断]"
        output = {
            "ok": True,
            "query": query,
            "domain": domain or "general",
            "brief": brief,
            "source": database_brief_client.DEFAULT_BRIEF_ENDPOINT,
        }
    else:
        output = {
            "ok": False,
            "error": "database_brief_unavailable",
            "message": result.error_message or "本地数据库 API 暂时不可用",
            "source": database_brief_client.DEFAULT_BRIEF_ENDPOINT,
        }

    return json.dumps(output, ensure_ascii=False, indent=2)


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / (1024 * 1024):.1f}MB"


# ---------------------------------------------------------------------------
# Tool specs for registry
# ---------------------------------------------------------------------------


READONLY_TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_current_conversation_context",
        description="读取当前会话的上下文摘要（目标、状态、约束等）",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    ToolSpec(
        name="list_project_files_readonly",
        description="列出项目目录下的文件（只读，仅项目内）",
        input_schema={
            "type": "object",
            "properties": {
                "relative_dir": {"type": "string", "description": "相对目录路径，默认项目根"},
                "max_results": {"type": "integer", "description": "最大结果数，默认50，上限100"},
            },
            "required": [],
        },
    ),
    ToolSpec(
        name="read_project_file_readonly",
        description="读取项目文件内容（只读，仅项目内文本文件）",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件相对路径"},
                "max_chars": {"type": "integer", "description": "最大字符数，默认6000"},
            },
            "required": ["path"],
        },
    ),
    ToolSpec(
        name="search_project_text_readonly",
        description="在项目文件中搜索文本（只读，仅项目内）",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "relative_dir": {"type": "string", "description": "搜索目录，默认项目根"},
                "max_results": {"type": "integer", "description": "最大结果数，默认20，上限50"},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="get_multica_bound_tasks_readonly",
        description="读取当前会话绑定的 Multica 任务摘要（只读）",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    ToolSpec(
        name="search_database_brief_readonly",
        description="通过本地数据库 API 检索知识和规则摘要（只读，仅 localhost）",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词或用户问题摘要"},
                "domain": {"type": "string", "description": "知识域：backend/ui_design/automation/general，可选"},
                "limit": {"type": "integer", "description": "返回数量上限，默认5，上限10"},
            },
            "required": ["query"],
        },
    ),
)


# ---------------------------------------------------------------------------
# Tool dispatch map
# ---------------------------------------------------------------------------

_TOOL_FUNCTIONS = {
    "get_current_conversation_context": get_current_conversation_context,
    "list_project_files_readonly": list_project_files_readonly,
    "read_project_file_readonly": read_project_file_readonly,
    "search_project_text_readonly": search_project_text_readonly,
    "get_multica_bound_tasks_readonly": get_multica_bound_tasks_readonly,
    "search_database_brief_readonly": search_database_brief_readonly,
}


def execute_readonly_tool(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> tuple[str, bool]:
    """Execute a readonly tool by name. Returns (output, is_error)."""
    func = _TOOL_FUNCTIONS.get(tool_name)
    if func is None:
        return f"未注册的工具: {tool_name}", True
    try:
        result = func(arguments, context=context, project_root=project_root)
        return result, False
    except Exception as exc:
        return f"工具执行异常: {exc}", True
