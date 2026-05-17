"""json_tool_protocol.py — Strict JSON-based tool protocol parser.

Parses DeepSeek responses for tool_call or final directives using a strict
single-JSON-object protocol. Non-JSON responses are treated as plain assistant
text (safe fallback).

Aligned with claw-code's stream event parsing pattern: extract structured
events from model output, classify them, and route appropriately.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolProtocolResult:
    """Parsed result from a model response."""

    kind: str  # "final", "tool_call", "plain_text"
    content: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] | None = None
    error: str = ""


class JsonToolProtocol:
    """Parse model responses for tool protocol directives.

    Aligned with claw-code's approach of extracting structured events from
    provider responses, but using a JSON-based protocol rather than native
    function calling.
    """

    ALLOWED_KINDS = frozenset({"final", "tool_call"})

    @staticmethod
    def parse(raw_text: str) -> ToolProtocolResult:
        """Parse model response text for tool protocol directives.

        Returns ToolProtocolResult with kind="plain_text" for any non-JSON
        or unrecognized input (safe fallback).
        """
        text = str(raw_text or "").strip()
        if not text:
            return ToolProtocolResult(kind="plain_text", content="")

        obj = _try_parse_single_json(text)
        if obj is None:
            return ToolProtocolResult(kind="plain_text", content=text)

        parsed = _parse_protocol_object(obj)
        if parsed is not None:
            return parsed

        return ToolProtocolResult(kind="plain_text", content=text)

    @staticmethod
    def build_tool_result_message(
        tool_call_id: str, tool_name: str, output: str, is_error: bool = False
    ) -> str:
        """Build tool_result context injection for second model call.

        Aligned with claw-code: tool results are fed back as structured
        messages so the model can incorporate them into its final answer.
        """
        status = "错误" if is_error else "成功"
        return (
            f"[工具结果] 工具 {tool_name} 执行{status}：\n{output}\n\n"
            f"请基于以上工具结果继续回答用户。不要要求用户重复指令。"
        )


def parse_tool_protocol_response(raw_text: str) -> ToolProtocolResult:
    """Convenience function — delegates to JsonToolProtocol.parse."""
    return JsonToolProtocol.parse(raw_text)


def extract_embedded_protocol_json(raw_text: str) -> ToolProtocolResult | None:
    """Scan mixed text for a single embedded protocol JSON object.

    Handles cases like:
        '好的，我来读取。{"type":"tool_call","tool_name":"x","arguments":{}}'

    Returns ToolProtocolResult if exactly one valid protocol JSON object is
    found; returns None if zero or multiple found, or if the text is already
    clean JSON.
    """
    text = str(raw_text or "")
    if not text:
        return None

    # If the entire text is already clean JSON, don't extract — let .parse() handle it
    stripped = text.strip()
    try:
        json.loads(stripped)
        return None  # already clean JSON
    except json.JSONDecodeError:
        pass

    # Scan for balanced {...} objects
    candidates = _find_balanced_json_objects(text)
    if not candidates:
        return None

    valid: list[dict[str, Any]] = []
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        kind = obj.get("type")
        if kind in JsonToolProtocol.ALLOWED_KINDS:
            valid.append(obj)

    if len(valid) == 1:
        return _parse_protocol_object(valid[0])

    # Multiple valid protocol objects → ambiguous, don't execute
    if len(valid) > 1:
        return ToolProtocolResult(
            kind="error",
            error="回复中包含多个工具请求 JSON，请只输出一个明确的操作。",
        )

    return None


def _find_balanced_json_objects(text: str) -> list[str]:
    """Find all balanced {...} substrings in text."""
    results: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "{":
            depth = 0
            start = i
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
                            results.append(text[start:j + 1])
                            i = j + 1
                            break
                j += 1
            else:
                i += 1
        else:
            i += 1
    return results


def _try_parse_single_json(text: str) -> dict[str, Any] | None:
    """Try to parse text as a single JSON object.

    Rejects arrays, multiple objects, and code-fenced JSON.
    """
    # Strip markdown code fences if present — but only if they wrap a single
    # JSON object; multiple objects inside a fence are rejected.
    unwrapped = _unwrap_code_fence(text)

    try:
        obj = json.loads(unwrapped)
    except json.JSONDecodeError:
        return None

    if not isinstance(obj, dict):
        return None  # reject arrays

    return obj


def _unwrap_code_fence(text: str) -> str:
    """Strip markdown code fences from JSON text."""
    lines = text.strip().splitlines()
    if len(lines) >= 3:
        first = lines[0].strip()
        last = lines[-1].strip()
        if first.startswith("```") and last == "```":
            inner = "\n".join(lines[1:-1]).strip()
            # Only unwrap if the inner content is a single JSON object
            try:
                parsed = json.loads(inner)
                if isinstance(parsed, dict):
                    return inner
            except json.JSONDecodeError:
                pass
            # If inner isn't a single JSON object, return original text
            # so it falls through to plain_text
            return inner
    return text


def _parse_protocol_object(obj: dict[str, Any]) -> ToolProtocolResult | None:
    """Validate and parse a JSON object as a protocol directive."""
    kind = obj.get("type")
    if kind not in JsonToolProtocol.ALLOWED_KINDS:
        return None

    if kind == "final":
        content = obj.get("content")
        if not isinstance(content, str):
            return ToolProtocolResult(
                kind="error",
                error="final directive missing content",
            )
        return ToolProtocolResult(kind="final", content=content.strip())

    if kind == "tool_call":
        tool_name = obj.get("tool_name")
        arguments = obj.get("arguments")
        if not isinstance(tool_name, str) or not tool_name.strip():
            return ToolProtocolResult(
                kind="error",
                error="tool_call missing tool_name",
            )
        if not isinstance(arguments, dict):
            return ToolProtocolResult(
                kind="error",
                error="tool_call arguments must be a JSON object",
            )
        return ToolProtocolResult(
            kind="tool_call",
            tool_name=tool_name.strip(),
            arguments=arguments,
        )

    return None
