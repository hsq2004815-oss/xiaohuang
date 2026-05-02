from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_SESSION_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_SESSION_TURNS = 5

_SESSION_EXIT_PHRASES = (
    "好了", "没事了", "不用了", "退出", "结束",
    "休息吧", "可以了", "停止", "闭嘴", "先这样",
)

SESSION_EXIT_REPLY = "好的，我先待命。"

_PUNCT_RE = re.compile(r"[\s,，.。!！?？;；:：、\-_()　]+")


@dataclass(frozen=True)
class ConversationSessionConfig:
    enabled: bool = False
    timeout_seconds: float = DEFAULT_SESSION_TIMEOUT_SECONDS
    max_turns: int = DEFAULT_MAX_SESSION_TURNS


def normalize_session_text(text: str) -> str:
    return _PUNCT_RE.sub("", str(text or "")).lower()


def is_session_exit_text(text: str) -> bool:
    normalized = normalize_session_text(text)
    if not normalized:
        return False
    return any(phrase in normalized for phrase in _SESSION_EXIT_PHRASES)


def should_continue_session(turn_count: int, config: ConversationSessionConfig) -> bool:
    if not config.enabled:
        return False
    if config.max_turns <= 0:
        return False
    return turn_count < config.max_turns
