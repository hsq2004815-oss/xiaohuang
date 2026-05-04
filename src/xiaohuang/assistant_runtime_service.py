from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from xiaohuang.overlay_state_service import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_RESULT,
    build_reply_result_text,
)


@dataclass
class AssistantRuntimeCallbacks:
    set_state: Callable[[str, str | None], None]
    log_warn: Callable[[str], None]
    debug_print: Callable[[str], None] | None = None
    wait: Callable[[float], bool] | None = None
    hide_overlay: Callable[[], None] | None = None


@dataclass(frozen=True)
class AssistantTurnOutcome:
    continue_loop: bool
    error: str | None = None


def handle_single_turn_reply_result(
    *,
    callbacks: AssistantRuntimeCallbacks,
    pipeline_result,  # ReplyPipelineResult
    command_text: str,
    assistant_name: str = "小黄",
    post_response_cooldown: float = 0,
    resident_hidden: bool = False,
) -> AssistantTurnOutcome:
    _debug = callbacks.debug_print
    _warn = callbacks.log_warn
    _state = callbacks.set_state
    _wait = callbacks.wait or (lambda _s: False)
    _hide = callbacks.hide_overlay

    _state(
        STATE_RESULT,
        build_reply_result_text(
            command_text,
            pipeline_result.reply_text,
            pipeline_result.source_note,
            assistant_name=assistant_name,
        ),
    )
    if pipeline_result.tts_error:
        _warn(pipeline_result.tts_error)
        _state(STATE_ERROR, pipeline_result.tts_error)

    if _debug is not None and post_response_cooldown > 0:
        _debug(f"Post-response cooldown: {post_response_cooldown:.1f}s")

    if _wait(post_response_cooldown):
        return AssistantTurnOutcome(continue_loop=False)

    _state(STATE_IDLE)
    if resident_hidden and _hide is not None:
        _hide()
    _wait(0.5)

    return AssistantTurnOutcome(continue_loop=True)
