"""tool_types.py — Core data structures for the tool runtime.

Aligned with claw-code's ToolUse / ToolResult / ContentBlock / PermissionMode
patterns, expressed as Python dataclasses adapted for XiaoHuang.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RiskLevel = Literal["readonly", "write", "dangerous"]
RISK_READONLY: RiskLevel = "readonly"
RISK_WRITE: RiskLevel = "write"
RISK_DANGEROUS: RiskLevel = "dangerous"

_VALID_TOOL_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")


@dataclass(frozen=True)
class ToolSpec:
    """Registered tool definition — aligns with claw-code ToolSpec."""

    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: RiskLevel = RISK_READONLY
    readonly: bool = True
    requires_confirmation: bool = False
    timeout_seconds: int = 30
    max_output_chars: int = 6000

    def __post_init__(self):
        if not _is_valid_tool_name(self.name):
            raise ValueError(f"invalid tool name: {self.name!r}")


@dataclass(frozen=True)
class ToolCall:
    """Parsed tool invocation request — aligns with claw-code ToolUse block."""

    id: str
    tool_name: str
    arguments: dict[str, Any]
    source: str = ""
    created_at: str = ""
    conversation_id: str = ""
    turn_id: str = ""


@dataclass(frozen=True)
class ToolResult:
    """Result of a tool execution — aligns with claw-code ToolResult block."""

    tool_call_id: str
    tool_name: str
    ok: bool
    output: str = ""
    error: str = ""
    truncated: bool = False
    elapsed_ms: int = 0
    created_at: str = ""


@dataclass(frozen=True)
class ToolPermissionDecision:
    """Permission evaluation outcome — aligns with claw-code PermissionOutcome."""

    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""
    risk_level: RiskLevel = RISK_READONLY


@dataclass(frozen=True)
class ToolTurnRecord:
    """One agent turn that may include tool rounds — aligns with claw-code TurnSummary."""

    id: str
    conversation_id: str
    user_message_id: str = ""
    first_assistant_message_id: str = ""
    final_assistant_message_id: str = ""
    status: str = ""
    tool_rounds: int = 0
    max_tool_rounds: int = 2
    created_at: str = ""
    completed_at: str = ""
    error: str = ""


def _is_valid_tool_name(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    if len(name) > 64:
        return False
    return all(ch in _VALID_TOOL_NAME_CHARS for ch in name)


ALLOW_DECISION = ToolPermissionDecision(allowed=True)
DENY_NOT_REGISTERED = ToolPermissionDecision(
    allowed=False, reason="tool not registered"
)
DENY_NOT_READONLY = ToolPermissionDecision(
    allowed=False, reason="only readonly tools are allowed in this mode"
)
DENY_SENSITIVE = ToolPermissionDecision(
    allowed=False, reason="tool targets sensitive path or data"
)
DENY_ARGUMENT_INVALID = ToolPermissionDecision(
    allowed=False, reason="tool arguments do not match schema"
)
