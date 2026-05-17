"""tool_runtime — Readonly tool protocol runtime (C5H-B).

Architecture aligned with claw-code's ToolRegistry / ToolUse / ToolResult /
PermissionPolicy / ConversationRuntime patterns, adapted to Python and
XiaoHuang's existing conversation + LLM pipeline.
"""

from xiaohuang.tool_runtime.tool_types import (
    ToolSpec,
    ToolCall,
    ToolResult,
    ToolPermissionDecision,
    ToolTurnRecord,
    RiskLevel,
    RISK_READONLY,
    RISK_WRITE,
    RISK_DANGEROUS,
)
from xiaohuang.tool_runtime.tool_registry import ToolRegistry
from xiaohuang.tool_runtime.tool_permission_service import ToolPermissionService
from xiaohuang.tool_runtime.json_tool_protocol import (
    JsonToolProtocol,
    parse_tool_protocol_response,
    ToolProtocolResult,
)
from xiaohuang.tool_runtime.tool_execution_service import ToolExecutionService
from xiaohuang.tool_runtime.tool_transcript_service import ToolTranscriptService
from xiaohuang.tool_runtime.agent_turn_loop import (
    run_readonly_tool_turn,
    ReadonlyToolTurnConfig,
    ReadonlyToolTurnResult,
)
