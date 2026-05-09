from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


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
    latency_ms: int = 0
    error: str = ""
