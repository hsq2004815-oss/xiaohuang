"""run_reader_service.py — readonly Multica runs / run-messages reader.

Reads Multica issue run history and run-message logs.
No create, no assign, no rerun, no Agent launch.
"""

from __future__ import annotations

import json
from typing import Callable

from xiaohuang.multica_integration.cli_client import Runner, run_multica_argv
from xiaohuang.multica_integration.models import (
    MulticaRunMessage,
    MulticaRunMessagesResult,
    MulticaRunsResult,
    MulticaRunSummary,
)
from xiaohuang.multica_integration.safety import (
    CONFIRMED_ISSUE_RUNS_KEY,
    CONFIRMED_RUN_MESSAGES_KEY,
    build_issue_runs_argv,
    build_run_messages_argv,
    is_safe_issue_id,
    is_safe_task_id,
)

_MAX_MESSAGE_CHARS = 1600


def read_issue_runs(
    *,
    issue_id: str,
    runner: Runner | None = None,
) -> MulticaRunsResult:
    """Read the list of runs for a Multica issue."""
    clean = str(issue_id or "").strip()
    if not clean:
        return MulticaRunsResult(
            ok=False,
            issue_id="",
            error_code="missing_issue_id",
            message="Issue ID / Identifier 不能为空。",
        )
    if not is_safe_issue_id(clean):
        return MulticaRunsResult(
            ok=False,
            issue_id=clean,
            error_code="invalid_issue_id",
            message="Issue ID / Identifier 格式不安全。",
        )

    try:
        argv = build_issue_runs_argv(issue_id=clean)
    except ValueError as exc:
        return MulticaRunsResult(
            ok=False,
            issue_id=clean,
            error_code=str(exc),
            message="无法构建 runs 命令。",
        )

    result = run_multica_argv(CONFIRMED_ISSUE_RUNS_KEY, argv, runner=runner)
    if not result.ok:
        return MulticaRunsResult(
            ok=False,
            issue_id=clean,
            raw_summary=result.stdout or result.stderr,
            error_code=result.error_code,
            message=result.message,
        )

    runs, warnings = _parse_runs_json(result.stdout, clean)
    return MulticaRunsResult(
        ok=True,
        issue_id=clean,
        runs=tuple(runs),
        raw_summary=result.stdout,
        warnings=tuple(warnings),
        message=f"读取到 {len(runs)} 条运行记录。",
    )


def read_run_messages(
    *,
    task_id: str,
    runner: Runner | None = None,
) -> MulticaRunMessagesResult:
    """Read the run-messages for a specific Multica task/run."""
    clean = str(task_id or "").strip()
    if not clean:
        return MulticaRunMessagesResult(
            ok=False,
            task_id="",
            error_code="missing_task_id",
            message="Task ID 不能为空。",
        )
    if not is_safe_task_id(clean):
        return MulticaRunMessagesResult(
            ok=False,
            task_id=clean,
            error_code="invalid_task_id",
            message="Task ID 格式不安全。",
        )

    try:
        argv = build_run_messages_argv(task_id=clean)
    except ValueError as exc:
        return MulticaRunMessagesResult(
            ok=False,
            task_id=clean,
            error_code=str(exc),
            message="无法构建 run-messages 命令。",
        )

    result = run_multica_argv(CONFIRMED_RUN_MESSAGES_KEY, argv, runner=runner)
    if not result.ok:
        return MulticaRunMessagesResult(
            ok=False,
            task_id=clean,
            raw_summary=result.stdout or result.stderr,
            error_code=result.error_code,
            message=result.message,
        )

    messages, warnings = _parse_run_messages_json(result.stdout, clean)
    review = _build_review_summary(messages, clean)
    return MulticaRunMessagesResult(
        ok=True,
        task_id=clean,
        messages=tuple(messages),
        raw_summary=result.stdout,
        review_summary=review,
        warnings=tuple(warnings),
        message=f"读取到 {len(messages)} 条消息。",
    )


# ── internal parsers ──

def _parse_runs_json(stdout: str, issue_id: str) -> tuple[list[MulticaRunSummary], list[str]]:
    warnings: list[str] = []
    runs: list[MulticaRunSummary] = []
    raw = str(stdout or "").strip()
    if not raw:
        warnings.append("runs 输出为空")
        return runs, warnings

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        warnings.append("runs 输出非 JSON 格式，保留原文")
        return runs, warnings

    items: list[dict] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("data") or data.get("runs") or data.get("items") or []
    if not isinstance(items, list):
        warnings.append("runs JSON 结构未识别")
        return runs, warnings

    for item in items:
        if not isinstance(item, dict):
            continue
        run_id = str(item.get("id") or item.get("run_id") or "")
        task_id = str(item.get("task_id") or item.get("run_id") or item.get("id") or "")
        runs.append(MulticaRunSummary(
            run_id=run_id,
            task_id=task_id,
            issue_id=str(item.get("issue_id") or issue_id),
            status=str(item.get("status") or item.get("state") or ""),
            agent=str(item.get("agent") or item.get("assignee") or ""),
            title=str(item.get("title") or item.get("name") or ""),
            started_at=str(item.get("started_at") or item.get("created_at") or ""),
            updated_at=str(item.get("updated_at") or item.get("completed_at") or ""),
            raw_summary=_compact_dict_text(item),
        ))
    return runs, warnings


def _parse_run_messages_json(stdout: str, task_id: str) -> tuple[list[MulticaRunMessage], list[str]]:
    warnings: list[str] = []
    messages: list[MulticaRunMessage] = []
    raw = str(stdout or "").strip()
    if not raw:
        warnings.append("run-messages 输出为空")
        return messages, warnings

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        warnings.append("run-messages 输出非 JSON 格式，保留原文")
        return messages, warnings

    items: list[dict] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        extracted = _extract_list_from_dict(data)
        if extracted is not None:
            items = extracted
        else:
            warnings.append("run-messages JSON 结构未识别")
            return messages, warnings

    if not isinstance(items, list):
        warnings.append("run-messages JSON 结构未识别")
        return messages, warnings

    for item in items:
        if not isinstance(item, dict):
            continue
        content = _extract_message_content(item)
        if len(content) > _MAX_MESSAGE_CHARS:
            content = content[:_MAX_MESSAGE_CHARS].rstrip() + "..."
        messages.append(MulticaRunMessage(
            message_id=str(item.get("id") or item.get("message_id") or ""),
            seq=str(item.get("seq") or ""),
            tool=str(item.get("tool") or ""),
            message_type=str(item.get("type") or item.get("message_type") or ""),
            role=str(item.get("role") or ""),
            author=str(item.get("author") or item.get("sender") or ""),
            content=content,
            created_at=str(item.get("created_at") or item.get("timestamp") or ""),
            raw_summary=_compact_dict_text(item),
        ))

    messages.sort(key=lambda m: _seq_sort_key(m.seq))
    return messages, warnings


def _seq_sort_key(seq: str) -> int:
    try:
        return int(seq)
    except (ValueError, TypeError):
        return 0


def _extract_list_from_dict(data: dict) -> list | None:
    candidates = ("data", "messages", "items", "events", "logs", "steps", "result")
    for key in candidates:
        val = data.get(key)
        if isinstance(val, list):
            return val

    task = data.get("task")
    if isinstance(task, dict):
        val = task.get("messages")
        if isinstance(val, list):
            return val

    list_vals = [v for v in data.values() if isinstance(v, list)]
    if len(list_vals) == 1:
        return list_vals[0]

    return None


def _extract_message_content(item: dict) -> str:
    content = item.get("content")
    if content is not None and str(content).strip():
        return str(content)

    text = item.get("text")
    if text is not None and str(text).strip():
        return str(text)

    message = item.get("message")
    if message is not None and str(message).strip():
        return str(message)

    output = item.get("output")
    if output is not None and str(output).strip():
        return str(output)

    summary = item.get("summary")
    if summary is not None and str(summary).strip():
        return str(summary)

    inp = item.get("input")
    if inp is not None:
        return _format_input(inp)

    return _compact_dict_text(item)


def _format_input(inp) -> str:
    if isinstance(inp, dict):
        parts: list[str] = []
        command = inp.get("command")
        if command and str(command).strip():
            parts.append(f"command: {command}")
        description = inp.get("description")
        if description and str(description).strip():
            parts.append(f"description: {description}")
        if parts:
            return "\n".join(parts)
        return _compact_dict_text(inp)
    return str(inp)


def _build_review_summary(messages: list[MulticaRunMessage], task_id: str) -> str:
    if not messages:
        return f"运行消息不足 (task_id={task_id})，无法判断最终完成质量。"

    tool_use_count = 0
    tool_result_count = 0
    tools_seen: set[str] = set()
    commands_seen: list[str] = []
    author_msgs: dict[str, int] = {}
    has_error = False
    has_complete = False
    status_changes: list[str] = []

    _ERROR_KW = ("error", "failed", "fail", "exception", "traceback",
                 "失败", "报错", "异常")
    _COMPLETE_KW = ("complete", "done", "finished", "success", "pass",
                    "完成", "成功", "通过")
    _STATUS_CHANGE_KW = ("in_review", "changed to", "状态变更",
                         "已分配", "已创建", "completed", "done")

    for m in messages:
        msg_type = m.message_type or ""
        if msg_type == "tool_use":
            tool_use_count += 1
        elif msg_type == "tool_result":
            tool_result_count += 1

        tool = m.tool.strip()
        if tool:
            tools_seen.add(tool)

        content_lower = (m.content or "").lower()
        if any(kw in content_lower for kw in _ERROR_KW):
            has_error = True
        if any(kw in content_lower for kw in _COMPLETE_KW):
            has_complete = True
        for kw in _STATUS_CHANGE_KW:
            idx = content_lower.find(kw)
            if idx >= 0:
                snippet = m.content[max(0, idx - 10):idx + len(kw) + 30]
                status_changes.append(snippet.strip())
                break

        author = m.author or m.tool or "unknown"
        author_msgs[author] = author_msgs.get(author, 0) + 1
        for line in (m.content or "").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("command:") or stripped.startswith("command:"):
                cmd = stripped.split(":", 1)[-1].strip()
                if cmd and cmd not in commands_seen:
                    commands_seen.append(cmd)

    parts: list[str] = [f"共 {len(messages)} 条消息"]

    if tool_use_count or tool_result_count:
        parts.append(f"工具事件：tool_use {tool_use_count} 条 / tool_result {tool_result_count} 条")
        if tools_seen:
            parts.append(f"涉及工具：{', '.join(sorted(tools_seen))}")
        if commands_seen:
            parts.append(f"发现命令：{', '.join(commands_seen[:5])}")
    else:
        parts.append(f"参与者: {', '.join(f'{k}({v})' for k, v in author_msgs.items())}")

    if status_changes:
        unique_changes = list(dict.fromkeys(status_changes))[:3]
        parts.append(f"发现状态变更：{'；'.join(unique_changes)}")

    if has_error and has_complete:
        parts.append("发现错误信号但也有完成信号，建议手动查看完整消息。")
    elif has_error:
        parts.append("发现错误信号，运行可能未成功完成。")
    elif has_complete:
        parts.append("发现完成信号，运行可能已成功，仍建议人工验收。")
    else:
        if tool_use_count or tool_result_count:
            parts.append("消息中未找到明确成功或失败信号，无法判断最终完成质量。")
        else:
            parts.append("消息中未找到明确成功或失败信号，无法判断最终完成质量。")

    return "；".join(parts)


def _compact_dict_text(item: dict) -> str:
    text = json.dumps(item, ensure_ascii=False, default=str)
    if len(text) > 400:
        return text[:400].rstrip() + "..."
    return text
