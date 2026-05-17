from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class TextInteractionMessage:
    role: Literal["user", "assistant"]
    text: str
    source: str = ""
    ts: str = ""


@dataclass(frozen=True)
class TextInteractionResult:
    ok: bool
    session_id: str
    user_text: str = ""
    reply_text: str = ""
    reply_source: str = ""
    has_llm_key: bool = False
    llm_configured: bool = False
    blocked_panel_command: bool = False
    requires_confirmation: bool = False
    pending_task: dict[str, Any] | None = None
    context_pack: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_rounds: int = 0
    latency_ms: int = 0
    error: str = ""
