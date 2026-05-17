"""agent_turn_loop.py — Readonly tool turn orchestrator.

Aligned with claw-code's ConversationRuntime.run_turn() pattern:
- Build system prompt with tool schemas
- Call model, parse response for tool_use or final
- Execute tools, push results back, loop until final or max_rounds

C5H-B: max 2 tool rounds, readonly tools only, JSON protocol.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from xiaohuang.tool_runtime.tool_types import (
    ToolCall,
    ToolResult,
    ToolTurnRecord,
)
from xiaohuang.tool_runtime.tool_registry import ToolRegistry, build_default_registry
from xiaohuang.tool_runtime.tool_permission_service import ToolPermissionService
from xiaohuang.tool_runtime.json_tool_protocol import (
    JsonToolProtocol,
    ToolProtocolResult,
)
from xiaohuang.tool_runtime.tool_execution_service import ToolExecutionService
from xiaohuang.tool_runtime.tool_transcript_service import ToolTranscriptService


@dataclass(frozen=True)
class ReadonlyToolTurnConfig:
    max_tool_rounds: int = 2
    enable_readonly_tools: bool = True
    project_root: Path = Path(r"E:\Projects\xiaohuang")


@dataclass(frozen=True)
class ReadonlyToolTurnResult:
    reply_text: str
    reply_source: str
    tool_rounds: int
    tool_calls: list[dict[str, Any]]
    final_assistant_message_id: str
    error: str = ""


def _make_id() -> str:
    import uuid

    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def run_readonly_tool_turn(
    *,
    conversation_id: str,
    user_text: str,
    context_pack_render: str,
    llm_call_func: Callable[..., Any],
    registry: ToolRegistry | None = None,
    transcript_service: ToolTranscriptService | None = None,
    config: ReadonlyToolTurnConfig | None = None,
    context: dict[str, Any] | None = None,
) -> ReadonlyToolTurnResult:
    """Run one agent turn with readonly tool loop.

    Flow:
    1. Build tool-augmented system prompt
    2. Call DeepSeek with context + tool protocol instructions
    3. If plain text or final, return directly
    4. If tool_call: parse, check permission, execute, record, re-call model
    5. Loop until final or max_tool_rounds reached

    Architecture aligned with claw-code ConversationRuntime.run_turn():
    - Single loop with configurable max iterations
    - Tool results fed back as structured messages
    - Errors become results, not crashes
    """
    cfg = config or ReadonlyToolTurnConfig()
    reg = registry or build_default_registry()
    protocol = JsonToolProtocol()

    tool_schema_text = reg.get_tool_schema_for_prompt()
    tool_instructions = _build_tool_instructions(tool_schema_text)

    # Inject tool instructions into the system prompt
    augmented_context = _build_augmented_context(context_pack_render, tool_instructions)

    tool_calls: list[dict[str, Any]] = []
    reply_text = ""
    final_assistant_id = ""
    tool_rounds = 0
    error = ""

    # First model call with tool context
    result = _call_llm(llm_call_func, augmented_context, user_text)
    reply_text = str(result.get("text", "") or "").strip()

    if not reply_text:
        return ReadonlyToolTurnResult(
            reply_text="",
            reply_source="llm_empty",
            tool_rounds=0,
            tool_calls=[],
            final_assistant_message_id="",
            error="模型返回为空",
        )

    parsed = protocol.parse(reply_text)

    # If plain_text, try embedded JSON extraction before giving up.
    # Model may have emitted natural language + a single JSON object.
    if parsed.kind == "plain_text":
        from xiaohuang.tool_runtime.json_tool_protocol import extract_embedded_protocol_json

        embedded = extract_embedded_protocol_json(reply_text)
        if embedded is not None and embedded.kind in ("tool_call", "final", "error"):
            parsed = embedded
            # Don't fall through to plain_text return — proceed to tool_call/final checks below
        else:
            return ReadonlyToolTurnResult(
                reply_text=reply_text,
                reply_source="llm",
                tool_rounds=0,
                tool_calls=[],
                final_assistant_message_id=_make_id(),
            )

    # If it's a final directive, extract the content
    if parsed.kind == "final":
        content = parsed.content.strip() if parsed.content else ""
        return ReadonlyToolTurnResult(
            reply_text=content or "我暂时没有生成有效回复。",
            reply_source="llm_final",
            tool_rounds=0,
            tool_calls=[],
            final_assistant_message_id=_make_id(),
        )

    # If embedded extraction returned an error (multi-JSON, unknown type, etc.)
    if parsed.kind == "error":
        return ReadonlyToolTurnResult(
            reply_text=_scrub_json_from_text(reply_text),
            reply_source="llm_error",
            tool_rounds=0,
            tool_calls=[],
            final_assistant_message_id=_make_id(),
            error=parsed.error,
        )

    # It's a tool_call — loop
    permission_service = ToolPermissionService()
    execution_service = ToolExecutionService(reg, permission_service, project_root=cfg.project_root)

    turn_id = _make_id()
    turn_created = _now_iso()
    current_context = reply_text  # feed tool results back

    while tool_rounds < cfg.max_tool_rounds:
        if parsed.kind == "error":
            error = parsed.error
            reply_text = ""  # clear raw JSON from first call
            break

        if parsed.kind == "final":
            reply_text = parsed.content
            break

        if parsed.kind == "plain_text":
            # Try embedded JSON extraction in tool-result response too
            from xiaohuang.tool_runtime.json_tool_protocol import extract_embedded_protocol_json

            embedded = extract_embedded_protocol_json(current_context)
            if embedded is not None and embedded.kind == "tool_call":
                parsed = embedded
                continue  # re-enter loop with the extracted tool_call
            if embedded is not None and embedded.kind == "final":
                reply_text = embedded.content if embedded.content else current_context
                break
            # No usable JSON embedded — treat current_context as final
            reply_text = current_context
            break

        if parsed.kind != "tool_call":
            break

        tool_rounds += 1

        tool_call = ToolCall(
            id=_make_id(),
            tool_name=parsed.tool_name,
            arguments=parsed.arguments or {},
            source="model_json",
            created_at=_now_iso(),
            conversation_id=conversation_id,
            turn_id=turn_id,
        )

        spec = reg.get_tool(parsed.tool_name)

        # Permission check
        decision = permission_service.evaluate(tool_call, spec)

        # Execute
        tool_result = execution_service.execute(tool_call, context=context)

        # Record
        if transcript_service:
            try:
                transcript_service.record_tool_call(tool_call, spec.risk_level if spec else "")
                transcript_service.record_tool_result(tool_result)
                transcript_service.record_permission(
                    tool_call.id, conversation_id, decision
                )
            except Exception:
                pass

        tool_calls.append({
            "tool_call_id": tool_call.id,
            "tool_name": tool_call.tool_name,
            "arguments": tool_call.arguments,
            "ok": tool_result.ok,
            "output": tool_result.output if tool_result.ok else tool_result.error,
            "truncated": tool_result.truncated,
            "elapsed_ms": tool_result.elapsed_ms,
        })

        # Build tool result context for next model call
        tool_result_text = protocol.build_tool_result_message(
            tool_result.tool_call_id,
            tool_result.tool_name,
            tool_result.output if tool_result.ok else tool_result.error,
            is_error=not tool_result.ok,
        )

        # Call model again with tool result
        next_context = (
            augmented_context + "\n" + tool_result_text
        )
        result = _call_llm(llm_call_func, next_context, user_text)
        next_text = str(result.get("text", "") or "").strip()
        parsed = protocol.parse(next_text)
        # Store unwrapped content so fallback never leaks raw JSON
        current_context = parsed.content if parsed.kind == "final" else next_text

    # Unwrap final JSON even when loop exited at max_tool_rounds boundary.
    # Override reply_text if it still looks like raw JSON (from first call
    # or from the loop body), but preserve content already unwrapped by the
    # loop's embedded extraction.
    reply_looks_raw = not reply_text or '"type"' in str(reply_text)[:200]
    if parsed.kind == "final" and parsed.content and reply_looks_raw:
        reply_text = parsed.content
    elif parsed.kind == "plain_text" and current_context and reply_looks_raw:
        reply_text = current_context

    if turn_id and transcript_service:
        # Finalize turn record
        try:
            transcript_service.record_turn(
                ToolTurnRecord(
                    id=turn_id,
                    conversation_id=conversation_id,
                    user_message_id="",
                    first_assistant_message_id="",
                    final_assistant_message_id=final_assistant_id,
                    status="completed" if not error else "error",
                    tool_rounds=tool_rounds,
                    max_tool_rounds=cfg.max_tool_rounds,
                    created_at=turn_created,
                    completed_at=_now_iso(),
                    error=error,
                )
            )
        except Exception:
            pass

    if error and not reply_text:
        reply_text = "我暂时没有生成有效回复。"

    # Tool-result fallback: when tools succeeded but model returned empty/invalid
    # final, build a safe fallback from the last successful tool output.
    if (not reply_text or reply_text == "我暂时没有生成有效回复。") and tool_calls:
        last_ok = _last_ok_tool_output(tool_calls)
        if last_ok:
            reply_text = last_ok

    # Final safety: if reply_text is still raw protocol JSON, replace it
    if reply_text and reply_text.strip().startswith("{"):
        parsed_final = protocol.parse(reply_text)
        if parsed_final.kind == "final" and parsed_final.content:
            reply_text = parsed_final.content
        else:
            reply_text = _build_tool_result_fallback(tool_calls) or "我暂时没有生成有效回复。"

    source = "llm_tool_turn" if tool_rounds > 0 else "llm"

    final_reply = reply_text if reply_text else current_context
    # Scrub any raw protocol JSON that leaked through (mixed text, exhausted
    # loops, rejected tools, etc.)
    if final_reply and ('"type":"tool_call"' in final_reply or '"type":"final"' in final_reply):
        final_reply = _scrub_json_from_text(final_reply)

    return ReadonlyToolTurnResult(
        reply_text=final_reply,
        reply_source=source,
        tool_rounds=tool_rounds,
        tool_calls=tool_calls,
        final_assistant_message_id=final_assistant_id or _make_id(),
        error=error,
    )


def _last_ok_tool_output(tool_calls: list[dict[str, Any]]) -> str:
    """Return a brief fallback from the last successful tool output."""
    for tc in reversed(tool_calls):
        if tc.get("ok") and tc.get("output"):
            return _format_tool_output_fallback(tc["tool_name"], tc["output"])
    return ""


def _build_tool_result_fallback(tool_calls: list[dict[str, Any]]) -> str:
    """Build a fallback reply from the last tool result, regardless of ok/error."""
    for tc in reversed(tool_calls):
        output = tc.get("output") or tc.get("error") or ""
        if output:
            return _format_tool_output_fallback(tc["tool_name"], output)
    return ""


def _format_tool_output_fallback(tool_name: str, output: str) -> str:
    """Format a tool result as user-visible fallback text."""
    max_lines = 15
    lines = output.splitlines()
    truncated = lines[:max_lines]
    body = "\n".join(truncated)
    if len(lines) > max_lines:
        body += f"\n（共 {len(lines)} 行，仅显示前 {max_lines} 行）"

    prefix = _TOOL_FALLBACK_PREFIX.get(tool_name, "工具执行结果如下：")
    return f"{prefix}\n\n{body}"


_TOOL_FALLBACK_PREFIX: dict[str, str] = {
    "list_project_files_readonly": "我已读取目录，结果如下：",
    "read_project_file_readonly": "我已读取该文件，以下是内容片段：",
    "search_project_text_readonly": "我已搜索到以下匹配结果：",
    "get_current_conversation_context": "当前对话上下文如下：",
}


def _scrub_json_from_text(text: str) -> str:
    """Remove raw JSON objects from text, keeping natural language parts."""
    import re

    if not text:
        return ""
    # Remove balanced {...} JSON objects
    cleaned = _remove_json_objects(text)
    cleaned = cleaned.strip()
    if cleaned:
        return cleaned
    return "我暂时没有生成有效回复。"


def _remove_json_objects(text: str) -> str:
    """Remove all balanced {...} strings from text."""
    result = []
    i = 0
    n = len(text)
    skip_until = 0
    while i < n:
        if i < skip_until:
            i = skip_until
            continue
        if text[i] == "{":
            depth = 0
            in_string = False
            escape = False
            j = i
            while j < n:
                ch = text[j]
                if escape:
                    escape = False
                    j += 1
                    continue
                if ch == "\\" and in_string:
                    escape = True
                    j += 1
                    continue
                if ch == '"':
                    in_string = not in_string
                elif not in_string:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            skip_until = j + 1
                            break
                j += 1
            else:
                result.append(text[i])
                i += 1
                continue
            i = skip_until
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def _build_tool_instructions(tool_schema_text: str) -> str:
    if not tool_schema_text:
        return ""
    return (
        "【只读工具系统】\n"
        "你可以请求读取项目本地信息。工具是只读的，不会修改任何文件。\n"
        "只有确实需要读取本地项目信息时才发起工具请求，否则直接正常回答。\n\n"
        f"{tool_schema_text}\n"
        "【格式要求 — 严格遵守】\n"
        "- 工具请求格式（严格单个 JSON 对象）：\n"
        '  {"type":"tool_call","tool_name":"<工具名>","arguments":{...}}\n'
        "- 最终回答格式：\n"
        '  {"type":"final","content":"你的回答内容"}\n'
        "- 整个回复必须是且仅是上述 JSON 对象。\n"
        "- 绝对禁止在 JSON 前后添加任何自然语言文字。\n"
        '- 绝对禁止在 JSON 前面加「好的」「让我来」等前置说明。\n'
        "- 不要使用 Markdown 代码块包裹 JSON。\n"
        "- 不要请求未列出的工具（包括写文件、shell、git、删除、外部 Agent）。\n"
        "- 不需要工具时直接正常回答即可，无需 JSON 格式。\n"
    )


def _build_augmented_context(context_pack_render: str, tool_instructions: str) -> str:
    parts = []
    if tool_instructions:
        parts.append(tool_instructions)
    if context_pack_render:
        parts.append(context_pack_render)
    return "\n\n".join(parts)


def _call_llm(
    func: Callable[..., Any],
    context: str,
    user_text: str,
) -> dict[str, Any]:
    """Wrapper around the LLM call function for safe invocation."""
    try:
        result = func(user_text, context=context)
        if isinstance(result, dict):
            return result
        if hasattr(result, "text"):
            return {"text": result.text}
        return {"text": str(result)}
    except Exception as exc:
        return {"text": "", "error": str(exc)}
