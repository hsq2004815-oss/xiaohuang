"""tool_execution_service.py — Unified tool execution with safety enforcement.

Aligned with claw-code's ToolExecutor trait: execute takes tool_name + input,
returns output or error. Permission is checked before execution. Errors are
returned as ToolResults, not raised to crash the turn.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from xiaohuang.tool_runtime.tool_types import (
    ToolCall,
    ToolResult,
    ToolPermissionDecision,
)
from xiaohuang.tool_runtime.tool_registry import ToolRegistry
from xiaohuang.tool_runtime.tool_permission_service import ToolPermissionService
from xiaohuang.tool_runtime.readonly_tools import execute_readonly_tool


class ToolExecutionService:
    """Execute tool calls with permission enforcement, timing, and error handling.

    Architecture aligned with claw-code:
    - execute() is the single entry point
    - Permission is checked before execution
    - Tool errors become ToolResult(ok=False), not exceptions
    - Output is truncated to respect max_output_chars
    """

    def __init__(
        self,
        registry: ToolRegistry,
        permission_service: ToolPermissionService,
        *,
        project_root: Path | None = None,
    ) -> None:
        self._registry = registry
        self._permission = permission_service
        self._project_root = project_root

    def execute(
        self,
        tool_call: ToolCall,
        *,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute a tool call with full safety chain.

        Returns ToolResult with ok=True/False. Never raises on tool logic
        errors — all are captured as results.
        """
        started = time.perf_counter()
        spec = self._registry.get_tool(tool_call.tool_name)

        decision = self._permission.evaluate(tool_call, spec)

        if not decision.allowed:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.tool_name,
                ok=False,
                error=decision.reason,
                elapsed_ms=elapsed_ms,
                created_at=_now_iso(),
            )

        max_chars = spec.max_output_chars if spec else 6000

        try:
            output, is_error = execute_readonly_tool(
                tool_call.tool_name,
                tool_call.arguments,
                context=context,
                project_root=self._project_root,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.tool_name,
                ok=False,
                error=_sanitize_error(str(exc)),
                elapsed_ms=elapsed_ms,
                created_at=_now_iso(),
            )

        truncated = False
        if len(output) > max_chars:
            output = output[:max_chars] + f"\n\n[输出已截断，原 {len(output)} 字符]"
            truncated = True

        elapsed_ms = int((time.perf_counter() - started) * 1000)

        return ToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.tool_name,
            ok=not is_error,
            output=output if not is_error else "",
            error=output if is_error else "",
            truncated=truncated,
            elapsed_ms=elapsed_ms,
            created_at=_now_iso(),
        )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _sanitize_error(msg: str) -> str:
    """Strip potentially sensitive info from error messages."""
    # Keep it simple — don't leak paths or system details
    if len(msg) > 500:
        msg = msg[:500] + "…"
    return msg
