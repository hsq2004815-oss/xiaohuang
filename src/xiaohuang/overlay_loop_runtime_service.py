"""overlay_loop_runtime_service.py

只负责 overlay 主循环调度；具体 wake / command / reply / session / tool / database
能力必须在独立 service 中实现。
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from typing import Callable

from xiaohuang.assistant_runtime_service import (
    AssistantRuntimeCallbacks,
    AssistantSessionCallbacks,
    AssistantTurnCallbacks,
    run_assistant_turn_from_command,
)
from xiaohuang.command_runtime_service import (
    record_command_transcribe as _record_command_transcribe,
)
from xiaohuang.conversation_session_service import ConversationSessionConfig
from xiaohuang.latency_metrics_service import LatencyTracker
from xiaohuang.reply_pipeline_service import ReplyPipelineConfig, ReplyPipelineResult
from xiaohuang.reply_runtime_service import generate_reply_runtime_result
from xiaohuang.stt_client_service import (
    SttServerError,
    SttServerUnavailable,
    request_transcription,
)
from xiaohuang.wake_loop_service import (
    STT_MODE_COMMAND,
    STT_MODE_WAKE_CHECK,
    WakeLoopOptions,
    WakeLoopResult,
    run_wake_loop_once,
)
from xiaohuang.wake_runtime_service import (
    WAKE_ENGINE_OPENWAKEWORD,
    WAKE_ENGINE_STT_TEXT,
    OpenWakeWordBridgeRuntime,
    OpenWakeWordBridgeRuntime as _OpenWakeWordBridgeRuntime,
    OpenWakeWordListenerHandle,
    WakeEngineLoopStopped,
    WakeEngineRuntimeConfig,
    WakeEngineRuntimeError,
    _log_runtime_message,
    _safe_print,
    create_openwakeword_adapter,
    handle_openwakeword_event,
    log_openwakeword_listener_status,
    run_openwakeword_listener,
    start_openwakeword_listener,
    stop_adapter_safely,
    stop_openwakeword_listener,
    wait_for_openwakeword_event,
    wake_engine_runtime_error,
)


@dataclass(frozen=True)
class OverlayLoopRuntimeConfig:
    wake_engine_mode: str
    wake_engine_runtime: WakeEngineRuntimeConfig | None
    session_config: ConversationSessionConfig
    enable_tts: bool = False
    enable_llm: bool = False
    post_response_cooldown: float = 0.0
    resident_hidden: bool = False
    debug: bool = False
    assistant_name: str = "小黄"


def run_overlay_runtime(
    *,
    app,
    stop_event: threading.Event,
    logger,
    options: WakeLoopOptions,
    runtime_config: OverlayLoopRuntimeConfig,
    pipeline_config: ReplyPipelineConfig,
    record_openwakeword_command: Callable[..., WakeLoopResult],
    make_llm_debug_handler: Callable[..., object] = lambda logger, debug: None,
    playback_warning: Callable[[str], None] = lambda msg: None,
    log_warning: Callable[[str], None] = lambda msg: None,
    print_wake_match: Callable[[object], None] | None = None,
) -> None:
    _debug_print = _safe_print if runtime_config.debug else None

    def _overlay_stt(path, server_url, *, mode: str):
        try:
            return request_transcription(path, server_url)
        except (SttServerUnavailable, SttServerError) as exc:
            if mode == STT_MODE_WAKE_CHECK:
                if runtime_config.debug:
                    _safe_print(f"Wake check STT failed, skipped this window: {exc}")
                logger.warning("Wake check STT failed, skipped this window: %s", exc)
                return {"text": ""}
            raise

    def _run_stt_text_turn(turn_tracker: LatencyTracker) -> WakeLoopResult:
        on_wake_shown: Callable[[], None] | None = None
        if runtime_config.resident_hidden:
            on_wake_shown = lambda: (
                app.show_overlay(),
                app.thread_safe_set_state("wake_detected"),
            )
        return run_wake_loop_once(
            options,
            on_state_change=_make_handle_wake_state(app),
            on_wake_text=(lambda text: _safe_print(f"Wake check transcription: {text}")) if runtime_config.debug else None,
            on_wake_match=print_wake_match if runtime_config.debug else None,
            on_command_text=(lambda text: _safe_print(f"Command transcription: {text}")) if runtime_config.debug else None,
            on_wake_detected=on_wake_shown,
            request_transcription_func=_overlay_stt,
            latency_tracker=turn_tracker,
        )

    def _generate_reply_pipeline_guarded(
        command_text: str,
        *,
        config: ReplyPipelineConfig,
        bridge_runtime: _OpenWakeWordBridgeRuntime | None,
        latency_tracker,
    ) -> ReplyPipelineResult:

        def _before_tts(text: str) -> None:
            if bridge_runtime is not None:
                bridge_runtime.mark_tts_started()
            app.thread_safe_set_state("speaking", text)

        def _after_tts() -> None:
            if bridge_runtime is not None:
                bridge_runtime.mark_tts_finished()

        return generate_reply_runtime_result(
            command_text,
            config=config,
            on_debug=make_llm_debug_handler(logger, runtime_config.debug),
            playback_warn=playback_warning,
            latency_tracker=latency_tracker,
            on_before_tts=_before_tts,
            on_after_tts=_after_tts,
        )

    openwakeword_bridge: _OpenWakeWordBridgeRuntime | None = None
    openwakeword_listener: OpenWakeWordListenerHandle | None = None
    wake_engine_mode = runtime_config.wake_engine_mode
    wake_engine_runtime = runtime_config.wake_engine_runtime
    if wake_engine_mode == WAKE_ENGINE_OPENWAKEWORD and wake_engine_runtime is not None:
        openwakeword_bridge = _OpenWakeWordBridgeRuntime(wake_engine_runtime.cooldown_seconds)
        try:
            openwakeword_listener = start_openwakeword_listener(
                app=app,
                runtime_config=wake_engine_runtime,
                bridge_runtime=openwakeword_bridge,
                logger=logger,
                debug=runtime_config.debug,
                stop_event=stop_event,
            )
        except WakeEngineRuntimeError as exc:
            if wake_engine_runtime.fallback_enabled:
                _log_runtime_message(logger, "warning", f"fallback_to_stt_text reason={exc}")
                wake_engine_mode = WAKE_ENGINE_STT_TEXT
            else:
                _log_runtime_message(logger, "error", f"openwakeword_listener_error error={exc}")
                app.thread_safe_set_state("error", str(exc))
                return

    _turn_callbacks = AssistantTurnCallbacks(
        set_state=lambda s, d=None: app.thread_safe_set_state(s, d),
        log_info=lambda msg: logger.info(msg),
        log_warning=log_warning,
        wait_seconds=lambda s: stop_event.wait(s),
        generate_reply=lambda text, lt: _generate_reply_pipeline_guarded(
            text,
            config=pipeline_config,
            bridge_runtime=openwakeword_bridge,
            latency_tracker=lt,
        ),
        debug_print=_debug_print,
    )

    _session_callbacks = AssistantSessionCallbacks(
        set_state=lambda s, d=None: app.thread_safe_set_state(s, d),
        log_info=lambda msg: logger.info(msg),
        wait_seconds=lambda s: stop_event.wait(s),
        record_followup=lambda max_s, lt: _record_command_transcribe(
            options=options,
            max_seconds=max_s,
            debug=runtime_config.debug,
            logger=logger,
            on_track_start=lambda name: _make_latency_track(lt)(name, start=True),
            on_track_end=lambda name: _make_latency_track(lt)(name, start=False),
        ),
        generate_reply=lambda text, lt: _generate_reply_pipeline_guarded(
            text,
            config=pipeline_config,
            bridge_runtime=openwakeword_bridge,
            latency_tracker=lt,
        ),
        debug_print=_debug_print,
        log_warning=log_warning,
        hide_overlay=app.hide_overlay if runtime_config.resident_hidden else None,
    )

    _single_turn_callbacks = AssistantRuntimeCallbacks(
        set_state=lambda s, d=None: app.thread_safe_set_state(s, d),
        log_warn=log_warning,
        debug_print=_debug_print,
        wait=lambda s: stop_event.wait(s),
        hide_overlay=app.hide_overlay if runtime_config.resident_hidden else None,
    )

    try:
        while not stop_event.is_set():
            try:
                turn_tracker = LatencyTracker()
                turn_tracker.start("turn_total_ms")

                if (
                    wake_engine_mode == WAKE_ENGINE_OPENWAKEWORD
                    and wake_engine_runtime is not None
                    and openwakeword_bridge is not None
                    and openwakeword_listener is not None
                ):
                    try:
                        result = _run_openwakeword_turn_from_listener(
                            app=app,
                            options=options,
                            listener=openwakeword_listener,
                            logger=logger,
                            debug=runtime_config.debug,
                            stop_event=stop_event,
                            latency_tracker=turn_tracker,
                            resident_hidden=runtime_config.resident_hidden,
                            request_transcription_func=_overlay_stt,
                            record_openwakeword_command=record_openwakeword_command,
                        )
                    except WakeEngineLoopStopped:
                        break
                    except WakeEngineRuntimeError as exc:
                        stop_openwakeword_listener(openwakeword_listener)
                        openwakeword_listener = None
                        if wake_engine_runtime.fallback_enabled:
                            wake_engine_mode = WAKE_ENGINE_STT_TEXT
                            result = _run_stt_text_turn(turn_tracker)
                        else:
                            app.thread_safe_set_state("error", str(exc))
                            break
                else:
                    result = _run_stt_text_turn(turn_tracker)
                if stop_event.is_set():
                    break
                if not run_assistant_turn_from_command(
                    command_text=result.command_text,
                    turn_tracker=turn_tracker,
                    callbacks=_turn_callbacks,
                    session_config=runtime_config.session_config,
                    session_callbacks=_session_callbacks,
                    single_turn_callbacks=_single_turn_callbacks,
                    assistant_name=runtime_config.assistant_name,
                    enable_tts=runtime_config.enable_tts,
                    post_response_cooldown=runtime_config.post_response_cooldown,
                    resident_hidden=runtime_config.resident_hidden,
                    debug=runtime_config.debug,
                ):
                    break
            except (SttServerUnavailable, SttServerError) as exc:
                if stop_event.is_set():
                    break
                logger.warning("Command STT failed: %s", exc)
                if runtime_config.debug:
                    _safe_print(f"Command STT failed: {exc}")
                app.thread_safe_set_state("error", f"STT 转写失败：{exc}")
                if stop_event.wait(2.0):
                    break
            except Exception as exc:
                if stop_event.is_set():
                    break
                logger.exception("Voice overlay wake loop failed.")
                app.thread_safe_set_state("error", str(exc))
                if stop_event.wait(2.0):
                    break
    finally:
        if openwakeword_listener is not None:
            stop_openwakeword_listener(openwakeword_listener)


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _make_handle_wake_state(app):
    def _handle(state: str, payload: str | None = None) -> None:
        if state == "result":
            return
        app.thread_safe_set_state(state, payload)
    return _handle


def _run_openwakeword_turn_from_listener(
    *,
    app,
    options: WakeLoopOptions,
    listener: OpenWakeWordListenerHandle,
    logger,
    debug: bool,
    stop_event: threading.Event,
    latency_tracker=None,
    resident_hidden: bool = False,
    request_transcription_func: Callable[..., dict] = request_transcription,
    record_openwakeword_command: Callable[..., WakeLoopResult],
) -> WakeLoopResult:
    event = wait_for_openwakeword_event(listener, stop_event)
    return record_openwakeword_command(
        event=event,
        app=app,
        options=options,
        bridge_runtime=listener.bridge_runtime,
        logger=logger,
        debug=debug,
        latency_tracker=latency_tracker,
        resident_hidden=resident_hidden,
        request_transcription_func=request_transcription_func,
    )


def _make_latency_track(tracker):
    if tracker is None:
        return lambda name, **kw: None
    def _t(name, *, start=False):
        if start:
            tracker.start(name)
        else:
            tracker.end(name)
    return _t
