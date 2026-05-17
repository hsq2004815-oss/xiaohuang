"""tool_registry.py — Centralized tool registry.

Aligned with claw-code's ToolRegistry pattern: all tools registered in one
place, schema lookup centralized, no scattered tool definitions.
"""

from __future__ import annotations

from typing import Any

from xiaohuang.tool_runtime.tool_types import ToolSpec, _is_valid_tool_name


class ToolRegistry:
    """Centralized registry for tool specs.

    Architecture aligned with claw-code's ToolRegistry:
    - register_tool validates and stores
    - get_tool for lookup
    - list_tools for enumeration
    - get_tool_schema_for_prompt generates model-facing definitions
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register_tool(self, spec: ToolSpec) -> None:
        if not _is_valid_tool_name(spec.name):
            raise ValueError(f"invalid tool name: {spec.name!r}")
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool name: {spec.name!r}")
        self._tools[spec.name] = spec

    def get_tool(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_tool_schema_for_prompt(self) -> str:
        """Generate model-facing tool definitions text.

        Produces a compact description listing available tools with their
        parameters and constraints, suitable for injection into the system
        prompt or user-facing context.
        """
        tools = sorted(self._tools.values(), key=lambda t: t.name)
        if not tools:
            return ""

        lines = ["可用只读工具：", ""]
        for tool in tools:
            lines.append(f"### {tool.name}")
            lines.append(f"描述：{tool.description}")
            lines.append(f"参数定义：{_format_schema(tool.input_schema)}")
            lines.append(f"输出上限：{tool.max_output_chars} 字符")
            lines.append("")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


def _format_schema(schema: dict[str, Any]) -> str:
    """Compact JSON schema representation for prompt injection."""
    import json

    return json.dumps(schema, ensure_ascii=False, indent=2)


def build_default_registry() -> ToolRegistry:
    """Build and return the C5H-B readonly tool registry with 4 tools."""
    from xiaohuang.tool_runtime.readonly_tools import READONLY_TOOL_SPECS

    registry = ToolRegistry()
    for spec in READONLY_TOOL_SPECS:
        registry.register_tool(spec)
    return registry
