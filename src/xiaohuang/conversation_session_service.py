from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_SESSION_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_SESSION_TURNS = 12
DEFAULT_FOLLOWUP_TIMEOUT_SECONDS = 12.0
DEFAULT_MAX_SESSION_SECONDS = 300.0
DEFAULT_MAX_NO_SPEECH_RETRIES = 2

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
    followup_timeout_seconds: float = DEFAULT_FOLLOWUP_TIMEOUT_SECONDS
    max_session_seconds: float = DEFAULT_MAX_SESSION_SECONDS
    max_no_speech_retries: int = DEFAULT_MAX_NO_SPEECH_RETRIES


def normalize_session_text(text: str) -> str:
    return _PUNCT_RE.sub("", str(text or "")).lower()


def is_session_exit_text(text: str) -> bool:
    normalized = normalize_session_text(text)
    if not normalized:
        return False
    return any(phrase in normalized for phrase in _SESSION_EXIT_PHRASES)


def get_followup_timeout_seconds(config: ConversationSessionConfig) -> float:
    if config.followup_timeout_seconds > 0:
        return config.followup_timeout_seconds
    if config.timeout_seconds > 0:
        return config.timeout_seconds
    return 1.0


def should_continue_session(
    turn_count: int,
    config: ConversationSessionConfig,
    *,
    elapsed_seconds: float | None = None,
    no_speech_retries: int = 0,
) -> bool:
    if not config.enabled:
        return False
    if config.max_turns <= 0:
        return False
    if turn_count >= config.max_turns:
        return False
    if elapsed_seconds is not None and elapsed_seconds >= config.max_session_seconds:
        return False
    if no_speech_retries > config.max_no_speech_retries:
        return False
    return True


def should_exit_for_no_speech(no_speech_retries: int, config: ConversationSessionConfig) -> bool:
    return no_speech_retries > config.max_no_speech_retries


def get_session_end_reason(
    *,
    turn_count: int,
    config: ConversationSessionConfig,
    elapsed_seconds: float,
    no_speech_retries: int,
    exit_phrase_detected: bool = False,
    stop_event_set: bool = False,
) -> str | None:
    if stop_event_set:
        return "stop_event"
    if exit_phrase_detected:
        return "exit_phrase"
    if turn_count >= config.max_turns:
        return "max_turns"
    if elapsed_seconds >= config.max_session_seconds:
        return "max_session_seconds"
    if no_speech_retries > config.max_no_speech_retries:
        return "no_speech"
    return None
