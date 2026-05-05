from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from xiaohuang.conversation_session_service import (
    SESSION_EXIT_REPLY,
    ConversationSessionConfig,
    get_followup_timeout_seconds,
    get_session_end_reason,
    is_session_exit_text,
    should_continue_session,
    should_exit_for_no_speech,
)
from xiaohuang.latency_metrics_service import LatencyTracker, format_latency_summary
from xiaohuang.overlay_state_service import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_REPLYING,
    STATE_RESULT,
    build_reply_result_text,
)

if TYPE_CHECKING:
    from xiaohuang.reply_pipeline_service import ReplyPipelineResult


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


@dataclass
class AssistantTurnCallbacks:
    """Callbacks for run_assistant_turn_from_command — per-turn reply orchestration."""
    set_state: Callable[[str, str | None], None]
    log_info: Callable[[str], None]
    log_warning: Callable[[str], None]
    wait_seconds: Callable[[float], bool]
    generate_reply: Callable[[str, Any], "ReplyPipelineResult"]
    debug_print: Callable[[str], None] | None = None


@dataclass
class AssistantSessionCallbacks:
    set_state: Callable[[str, str | None], None]
    log_info: Callable[[str], None]
    wait_seconds: Callable[[float], bool]
    record_followup: Callable[[float, Any], str]
    generate_reply: Callable[[str, Any], "ReplyPipelineResult"]
    debug_print: Callable[[str], None] | None = None
    log_warning: Callable[[str], None] | None = None
    hide_overlay: Callable[[], None] | None = None


@dataclass(frozen=True)
class AssistantSessionOutcome:
    completed_turns: int
    end_reason: str
    no_speech_retries: int
    should_continue_main_loop: bool


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


def run_session_followup_loop(
    *,
    session_config: ConversationSessionConfig,
    callbacks: AssistantSessionCallbacks,
    initial_turn_count: int = 1,
    session_start_time: float,
    enable_tts: bool = False,
    post_response_cooldown: float = 0,
    debug: bool = False,
    now_func=time.perf_counter,
) -> AssistantSessionOutcome:
    _cb = callbacks

    turn_count = initial_turn_count
    no_speech_retries = 0
    exit_phrase_detected = False
    stop_requested_in_loop = False

    while (
        should_continue_session(
            turn_count,
            session_config,
            elapsed_seconds=now_func() - session_start_time,
            no_speech_retries=no_speech_retries,
        )
    ):
        followup_timeout = get_followup_timeout_seconds(session_config)
        st = LatencyTracker()
        st.start("turn_total_ms")

        if debug:
            _emit_debug(_cb.debug_print,
                f"Session turn {turn_count + 1}/{session_config.max_turns} "
                f"(follow-up window: {followup_timeout:.1f}s)"
            )

        _cb.set_state(STATE_LISTENING, "你还可以继续说")

        next_text = _cb.record_followup(followup_timeout, st)

        if _cb.wait_seconds(0):
            stop_requested_in_loop = True
            break

        if not next_text:
            no_speech_retries += 1
            if debug:
                _emit_debug(_cb.debug_print,
                    f"Session no speech retry {no_speech_retries}/{session_config.max_no_speech_retries + 1}"
                )
            if should_exit_for_no_speech(no_speech_retries, session_config):
                _cb.log_info("Session ended: no_speech")
                break
            continue

        if debug:
            _emit_debug(_cb.debug_print, f"Session command: {next_text}")

        no_speech_retries = 0

        if is_session_exit_text(next_text):
            if debug:
                _emit_debug(_cb.debug_print, "Session exit phrase detected")
            pipeline_result = _cb.generate_reply(next_text, st)
            _emit_print(_cb.debug_print, f"XiaoHuang: {pipeline_result.reply_text}")
            _cb.log_info(f"Overlay reply: {pipeline_result.reply_text} (source={pipeline_result.reply_source})")
            st.end("turn_total_ms")
            _cb.log_info(format_latency_summary(st.summary_ms(), turn=turn_count + 1, source=pipeline_result.reply_source))
            _cb.set_state(
                STATE_RESULT,
                build_reply_result_text(
                    next_text,
                    pipeline_result.reply_text,
                    getattr(pipeline_result, "source_note", None),
                    assistant_name="小黄",
                ),
            )
            exit_phrase_detected = True
            turn_count += 1
            if _cb.wait_seconds(post_response_cooldown):
                stop_requested_in_loop = True
                break
            break

        pipeline_result = _cb.generate_reply(next_text, st)
        _emit_print(_cb.debug_print, f"XiaoHuang reply: {pipeline_result.reply_text}")
        _emit_print(_cb.debug_print, f"Reply source: {pipeline_result.reply_source}")
        st.end("turn_total_ms")
        _cb.log_info(format_latency_summary(st.summary_ms(), turn=turn_count + 1, source=pipeline_result.reply_source))
        _cb.log_info(f"Overlay reply: {pipeline_result.reply_text} (source={pipeline_result.reply_source})")
        if pipeline_result.tts_error:
            if _cb.log_warning is not None:
                _cb.log_warning(pipeline_result.tts_error)
        if _cb.wait_seconds(0.3):
            stop_requested_in_loop = True
            break
        turn_count += 1

    reason = get_session_end_reason(
        turn_count=turn_count,
        config=session_config,
        elapsed_seconds=now_func() - session_start_time,
        no_speech_retries=no_speech_retries,
        exit_phrase_detected=exit_phrase_detected,
        stop_event_set=stop_requested_in_loop,
    )
    if reason:
        session_elapsed = now_func() - session_start_time
        _cb.log_info(
            f"Session ended: reason={reason} completed_turns={turn_count} max_turns={session_config.max_turns} "
            f"elapsed_seconds={session_elapsed:.1f} max_session_seconds={session_config.max_session_seconds} "
            f"no_speech_retries={no_speech_retries} max_no_speech_retries={session_config.max_no_speech_retries}"
        )

    cooldown_wait = 0.5 if post_response_cooldown > 0 else 0
    stop_requested = _cb.wait_seconds(cooldown_wait)
    if not stop_requested:
        _cb.set_state(STATE_IDLE)
        if _cb.hide_overlay is not None:
            _cb.hide_overlay()
        _cb.wait_seconds(0.5)

    return AssistantSessionOutcome(
        completed_turns=turn_count,
        end_reason=reason or "unknown",
        no_speech_retries=no_speech_retries,
        should_continue_main_loop=not stop_requested,
    )


def run_assistant_turn_from_command(
    *,
    command_text: str,
    turn_tracker,
    callbacks: AssistantTurnCallbacks,
    session_config: ConversationSessionConfig,
    session_callbacks: AssistantSessionCallbacks,
    single_turn_callbacks: AssistantRuntimeCallbacks,
    assistant_name: str = "小黄",
    enable_tts: bool = False,
    post_response_cooldown: float = 0,
    resident_hidden: bool = False,
    debug: bool = False,
) -> bool:
    """Process one assistant turn from command_text. Returns True to continue main loop."""
    _cb = callbacks

    if not command_text or not command_text.strip():
        return True

    _cb.log_info(f"Overlay command transcription: {command_text}")
    _cb.set_state(STATE_REPLYING)

    pipeline_result = _cb.generate_reply(command_text, turn_tracker)

    if debug:
        _emit_debug(_cb.debug_print, f"XiaoHuang reply: {pipeline_result.reply_text}")
        _emit_debug(_cb.debug_print, f"Reply source: {pipeline_result.reply_source}")
        turn_tracker.end("turn_total_ms")
        summary = turn_tracker.summary_ms()
        if summary:
            _emit_debug(_cb.debug_print,
                format_latency_summary(summary, turn=1, source=pipeline_result.reply_source))
    turn_tracker.end("turn_total_ms")
    _cb.log_info(format_latency_summary(turn_tracker.summary_ms(), turn=1, source=pipeline_result.reply_source))
    _cb.log_info(f"Overlay reply: {pipeline_result.reply_text} (source={pipeline_result.reply_source})")

    if pipeline_result.tts_error:
        _cb.log_warning(pipeline_result.tts_error)

    if session_config.enabled:
        if _cb.wait_seconds(0.3):
            return False
        outcome = run_session_followup_loop(
            session_config=session_config,
            callbacks=session_callbacks,
            session_start_time=time.perf_counter(),
            enable_tts=enable_tts,
            post_response_cooldown=post_response_cooldown,
            debug=debug,
        )
        return outcome.should_continue_main_loop

    turn_outcome = handle_single_turn_reply_result(
        callbacks=single_turn_callbacks,
        pipeline_result=pipeline_result,
        command_text=command_text,
        assistant_name=assistant_name,
        post_response_cooldown=post_response_cooldown,
        resident_hidden=resident_hidden,
    )
    return turn_outcome.continue_loop


def _emit_debug(debug_print: Callable[[str], None] | None, message: str) -> None:
    if debug_print is not None:
        debug_print(message)


def _emit_print(debug_print: Callable[[str], None] | None, message: str) -> None:
    if debug_print is not None:
        debug_print(message)
