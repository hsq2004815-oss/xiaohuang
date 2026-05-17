"""tool_permission_service.py — Centralized permission evaluation.

Aligned with claw-code's PermissionPolicy pattern: single authorization point
that checks tool requirements against current mode, deny/allow rules.

C5H-B policy: only readonly tools are allowed. shell/write/delete/git/
external_agent/dangerous are all denied.
"""

from __future__ import annotations

from typing import Any

from xiaohuang.tool_runtime.tool_types import (
    ToolCall,
    ToolPermissionDecision,
    ToolSpec,
    ALLOW_DECISION,
    DENY_NOT_REGISTERED,
    DENY_NOT_READONLY,
)

_DENIED_RISK_LEVELS = frozenset({"write", "dangerous"})
_DENIED_TOOL_NAME_PREFIXES = (
    "shell",
    "bash",
    "write",
    "edit",
    "delete",
    "remove",
    "git",
    "external",
    "dangerous",
)


class ToolPermissionService:
    """Central permission evaluator for tool calls.

    Architecture aligned with claw-code PermissionPolicy:
    - Single authorize() entry point
    - Mode-based evaluation (only readonly allowed in C5H-B)
    - Tool name pattern blocking
    - Schema validation
    - Readonly-only policy enforcement
    """

    def __init__(self) -> None:
        pass

    def evaluate(
        self,
        tool_call: ToolCall,
        tool_spec: ToolSpec | None,
        user_text: str = "",
    ) -> ToolPermissionDecision:
        """Evaluate whether a tool call is allowed.

        Parameters:
            tool_call: The parsed tool invocation request.
            tool_spec: The registered tool spec, or None if not registered.
            user_text: The current user message (for context, not authorization).

        Returns ToolPermissionDecision with allowed=True/False and reason.
        """
        if tool_spec is None:
            return DENY_NOT_REGISTERED

        if tool_spec.risk_level in _DENIED_RISK_LEVELS:
            return ToolPermissionDecision(
                allowed=False,
                reason=f"tool {tool_call.tool_name!r} has forbidden risk level {tool_spec.risk_level!r}; only readonly tools allowed",
                risk_level=tool_spec.risk_level,
            )

        if not tool_spec.readonly:
            return DENY_NOT_READONLY

        if self._is_denied_tool_name(tool_call.tool_name):
            return ToolPermissionDecision(
                allowed=False,
                reason=f"tool {tool_call.tool_name!r} matches denied name pattern (shell/write/delete/git/dangerous)",
            )

        if not self._validate_arguments(tool_call.arguments, tool_spec.input_schema):
            return ToolPermissionDecision(
                allowed=False,
                reason=f"tool {tool_call.tool_name!r} arguments do not match input schema",
            )

        if tool_spec.requires_confirmation:
            return ToolPermissionDecision(
                allowed=False,
                requires_confirmation=True,
                reason=f"tool {tool_call.tool_name!r} requires user confirmation (not yet supported in C5H-B)",
            )

        return ALLOW_DECISION

    @staticmethod
    def _is_denied_tool_name(name: str) -> bool:
        """Check if tool name matches a denied pattern."""
        normalized = name.lower()
        return normalized.startswith(_DENIED_TOOL_NAME_PREFIXES)

    @staticmethod
    def _validate_arguments(
        arguments: dict[str, Any], schema: dict[str, Any]
    ) -> bool:
        """Basic schema validation for tool arguments.

        Checks required fields are present and types are compatible.
        This is a lightweight check; security path validation is done by
        the readonly_tools module.
        """
        if not isinstance(arguments, dict):
            return False

        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in arguments:
                    return False

        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool}
            for key, value in arguments.items():
                prop = properties.get(key, {})
                expected_type = prop.get("type")
                if expected_type and expected_type in type_map:
                    expected = type_map[expected_type]
                    if not isinstance(value, expected):
                        return False

        return True
