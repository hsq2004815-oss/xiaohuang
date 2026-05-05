from __future__ import annotations

import argparse
import queue
from dataclasses import dataclass
import math
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.config_service import load_config
from xiaohuang.latency_metrics_service import (
    LatencyTracker,
    format_latency_summary,
)
from xiaohuang.conversation_session_service import ConversationSessionConfig
from xiaohuang.logging_service import configure_logging
from xiaohuang.llm_reply_service import load_llm_provider_config
from xiaohuang.overlay_state_service import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_REPLYING,
    STATE_RESULT,
    STATE_SPEAKING,
    STATE_TRANSCRIBING,
    STATE_WAKE_CHECKING,
    STATE_WAKE_DETECTED,
    build_reply_result_text,
    build_server_unavailable_status,
    get_overlay_status_text,
)
from xiaohuang.overlay_runtime_service import resolve_post_response_cooldown
from xiaohuang.reply_pipeline_service import (
    ReplyPipelineConfig,
    ReplyPipelineResult,
    generate_reply_pipeline_result,
)
from xiaohuang.assistant_runtime_service import (
    AssistantRuntimeCallbacks,
    AssistantSessionCallbacks,
    AssistantTurnOutcome,
    handle_single_turn_reply_result,
    run_session_followup_loop,
)
from xiaohuang.reply_runtime_service import generate_reply_runtime_result
from xiaohuang.app_config_service import apply_cli_overrides, load_config as load_user_config
from xiaohuang.audio_capture_service import build_recording_path
from xiaohuang.command_runtime_service import (
    CommandRecordResult,
    call_overlay_transcription as _call_overlay_transcription,
    record_and_transcribe,
    record_command_transcribe as _record_command_transcribe,
)
from xiaohuang.stt_client_service import SttServerError, SttServerUnavailable, check_server_health, request_transcription
from xiaohuang.tts_service import DEFAULT_TTS_VOICE
from xiaohuang.vad_recording_service import record_until_silence
from xiaohuang.wake_command_bridge_service import WakeCommandBridge, WakeCommandBridgeConfig
from xiaohuang.wake_engine_service import WakeEvent
from xiaohuang.wake_loop_service import STT_MODE_COMMAND, STT_MODE_WAKE_CHECK, WakeLoopOptions, WakeLoopResult, run_wake_loop_once
from xiaohuang.wake_runtime_service import (
    OPENWAKEWORD_QUEUE_POLL_SECONDS,
    OPENWAKEWORD_STATUS_INTERVAL_SECONDS,
    WAKE_ENGINE_OPENWAKEWORD,
    WAKE_ENGINE_STT_TEXT,
    WakeEngineLoopStopped,
    WakeEngineRuntimeConfig,
    WakeEngineRuntimeError,
    WakeEngineRuntimePlan,
    OpenWakeWordBridgeRuntime,
    OpenWakeWordBridgeRuntime as _OpenWakeWordBridgeRuntime,
    OpenWakeWordListenerHandle,
    build_wake_engine_runtime_config as _build_wake_engine_runtime_config,
    create_openwakeword_adapter as _create_openwakeword_adapter,
    format_openwakeword_dependency_error as _format_openwakeword_dependency_error,
    handle_openwakeword_event as _handle_openwakeword_event,
    log_openwakeword_listener_status as _log_openwakeword_listener_status,
    normalize_wake_engine as _normalize_wake_engine,
    run_openwakeword_listener as _run_openwakeword_listener,
    select_wake_engine_runtime as _select_wake_engine_runtime,
    start_openwakeword_listener as _start_openwakeword_listener,
    stop_adapter_safely as _stop_adapter_safely,
    stop_openwakeword_listener as _stop_openwakeword_listener,
    wait_for_openwakeword_event as _wait_for_openwakeword_event,
    wake_engine_runtime_error as _wake_engine_runtime_error,
)
from xiaohuang.wake_word_service import DEFAULT_WAKE_ALIASES, WakeMatchResult, parse_wake_phrases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the XiaoHuang Tkinter voice overlay prototype.")
    parser.add_argument("--device", type=int, default=None, help="Input device ID. Defaults to config audio.device_id or 0.")
    parser.add_argument("--server-url", default="http://127.0.0.1:8766", help="Local STT server URL.")
    parser.add_argument("--wake-window-seconds", type=float, default=3.0, help="Short recording window for wake checks. Defaults to 3.")
    parser.add_argument("--wake-phrases", default=None, help="Comma-separated wake phrases. Defaults to config or '小黄,小黄小黄'.")
    parser.add_argument("--wake-aliases", default=None, help="Comma-separated low-confidence wake aliases.")
    parser.add_argument("--max-seconds", type=float, default=10.0, help="Maximum VAD command recording duration. Defaults to 10.")
    parser.add_argument("--silence-seconds", type=float, default=0.8, help="Silence duration after command speech before VAD stops.")
    parser.add_argument("--debug", action="store_true", help="Print wake-window and command transcription debug output.")
    parser.add_argument("--enable-tts", action="store_true", help="Generate and play a one-sentence TTS reply after transcription.")
    parser.add_argument("--tts-voice", default=DEFAULT_TTS_VOICE, help="edge-tts voice name.")
    parser.add_argument("--tts-output-dir", default="data/tts", help="Directory for generated TTS MP3 files.")
    parser.add_argument("--enable-llm", action="store_true", help="Use DeepSeek single-turn reply when API key is configured.")
    parser.add_argument("--llm-timeout", type=float, default=15.0, help="DeepSeek request timeout in seconds.")
    parser.add_argument("--llm-model", default=None, help="DeepSeek model override. Defaults to DEEPSEEK_MODEL or deepseek-v4-flash.")
    parser.add_argument("--llm-base-url", default=None, help="DeepSeek base URL override. Defaults to DEEPSEEK_BASE_URL or https://api.deepseek.com.")
    parser.add_argument("--llm-max-tokens", type=int, default=None, help="DeepSeek max_tokens. Defaults to DEEPSEEK_MAX_TOKENS or 96.")
    parser.add_argument(
        "--post-response-cooldown",
        type=float,
        default=None,
        help="Seconds to pause before listening again after a reply. Defaults to 6 with TTS, 3.5 without TTS.",
    )
    parser.add_argument(
        "--resident-hidden",
        action="store_true",
        help="Start hidden and show overlay only after wake word is detected.",
    )
    parser.add_argument(
        "--conversation-session",
        action="store_true",
        help="Keep listening for follow-up commands after wake without re-waking.",
    )
    parser.add_argument(
        "--session-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for follow-up commands in conversation session.",
    )
    parser.add_argument(
        "--max-session-turns",
        type=int,
        default=12,
        help="Maximum turns in one active conversation session.",
    )
    parser.add_argument(
        "--followup-timeout",
        type=float,
        default=12.0,
        help="Seconds to wait for follow-up speech after each reply.",
    )
    parser.add_argument(
        "--max-session-seconds",
        type=float,
        default=300.0,
        help="Maximum total seconds for one conversation session.",
    )
    parser.add_argument(
        "--max-no-speech-retries",
        type=int,
        default=2,
        help="Exit session after this many no-speech follow-up attempts.",
    )
    parser.add_argument("--config", default=None, help="Path to config.json. Defaults to %%USERPROFILE%%\\.xiaohuang\\config.json")
    return parser.parse_args()


def _print_wake_engine_runtime_config(
    runtime_config: WakeEngineRuntimeConfig,
    selected_engine: str,
    logger,
) -> None:
    for message in (
        f"wake_engine_selected={selected_engine}",
        f"wake_fallback_enabled={_bool_text(runtime_config.fallback_enabled)}",
        f"wake_device_index={runtime_config.device}",
        f"wake_cooldown_seconds={runtime_config.cooldown_seconds}",
        f"wake_sensitivity={runtime_config.sensitivity}",
    ):
        _log_runtime_message(logger, "info", message)


class VoiceOverlayApp:
    def __init__(
        self,
        root,
        *,
        stop_event: threading.Event,
        debug: bool = False,
        start_hidden: bool = False,
        title: str = "小黄",
        wake_phrase: str = "小黄",
    ) -> None:
        self.root = root
        self.stop_event = stop_event
        self.debug = debug
        self.assistant_name = title or "小黄"
        self.wake_phrase = wake_phrase or "小黄"
        self.state = STATE_IDLE
        self.phase = 0.0
        self.closed = False
        self._after_ids: set[str] = set()
        self._build_ui(title)
        self.set_state(STATE_IDLE)
        self._animate()
        if start_hidden:
            try:
                self.root.withdraw()
            except Exception:
                pass

    def _build_ui(self, title: str = "小黄") -> None:
        self.root.title(title)
        self.root.geometry("360x120+80+80")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        try:
            self.root.overrideredirect(True)
        except Exception:
            pass

        import tkinter as tk

        self.frame = tk.Frame(self.root, bg="#101418", bd=1, relief="solid")
        self.frame.pack(fill="both", expand=True)
        self.title_label = tk.Label(
            self.frame,
            text="",
            bg="#101418",
            fg="#f5f7fa",
            font=("Microsoft YaHei UI", 16, "bold"),
            anchor="w",
        )
        self.title_label.pack(fill="x", padx=18, pady=(14, 2))
        self.subtitle_label = tk.Label(
            self.frame,
            text="",
            bg="#101418",
            fg="#aeb7c2",
            font=("Microsoft YaHei UI", 10),
            anchor="w",
            wraplength=320,
            justify="left",
        )
        self.subtitle_label.pack(fill="x", padx=18)
        self.canvas = tk.Canvas(self.frame, width=320, height=34, bg="#101418", highlightthickness=0)
        self.canvas.pack(fill="x", padx=18, pady=(4, 10))

        self.frame.bind("<ButtonPress-1>", self._start_move)
        self.frame.bind("<B1-Motion>", self._move)
        self.title_label.bind("<ButtonPress-1>", self._start_move)
        self.title_label.bind("<B1-Motion>", self._move)
        self.subtitle_label.bind("<ButtonPress-1>", self._start_move)
        self.subtitle_label.bind("<B1-Motion>", self._move)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _event: self.close())

    def _start_move(self, event) -> None:
        self._drag_x = event.x
        self._drag_y = event.y

    def _move(self, event) -> None:
        try:
            x = self.root.winfo_x() + event.x - self._drag_x
            y = self.root.winfo_y() + event.y - self._drag_y
            self.root.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def set_state(self, state: str, detail: str | None = None) -> None:
        if self.closed:
            return
        status = get_overlay_status_text(
            state,
            detail,
            assistant_name=self.assistant_name,
            wake_phrase=self.wake_phrase,
        )
        self.state = status.state
        try:
            self.title_label.configure(text=status.title)
            self.subtitle_label.configure(text=status.subtitle)
        except tk.TclError:
            self.closed = True

    def thread_safe_set_state(self, state: str, detail: str | None = None) -> None:
        self._safe_after(0, lambda: self.set_state(state, detail))

    def show_status(self, status) -> None:
        if self.closed:
            return
        self.state = status.state
        try:
            self.title_label.configure(text=status.title)
            self.subtitle_label.configure(text=status.subtitle)
        except tk.TclError:
            self.closed = True

    def thread_safe_show_status(self, status) -> None:
        self._safe_after(0, lambda: self.show_status(status))

    def schedule_idle(self, delay_ms: int = 3500) -> None:
        self._safe_after(delay_ms, lambda: self.set_state(STATE_IDLE))

    def show_overlay(self) -> None:
        def _show() -> None:
            try:
                if not self.root.winfo_exists():
                    return
                self.root.deiconify()
                self.root.lift()
                self.root.attributes("-topmost", True)
                self.root.after(300, lambda: self.root.attributes("-topmost", True))
            except Exception:
                pass
        try:
            self.root.after(0, _show)
        except Exception:
            pass

    def hide_overlay(self) -> None:
        def _hide() -> None:
            try:
                if not self.root.winfo_exists():
                    return
                self.root.withdraw()
            except Exception:
                pass
        try:
            self.root.after(0, _hide)
        except Exception:
            pass

    def _animate(self) -> None:
        if self.closed:
            return
        try:
            self.canvas.delete("all")
        except tk.TclError:
            self.closed = True
            return
        amplitude = self._amplitude_for_state()
        color = self._color_for_state()
        for index in range(8):
            x = 18 + index * 36
            height = 6 + amplitude * (0.35 + 0.65 * abs(math.sin(self.phase + index * 0.7)))
            y1 = 18 - height / 2
            y2 = 18 + height / 2
            try:
                self.canvas.create_rectangle(x, y1, x + 14, y2, fill=color, outline="")
            except tk.TclError:
                self.closed = True
                return
        self.phase += 0.28
        self._safe_after(90, self._animate)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.stop_event.set()
        for after_id in list(self._after_ids):
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        self._after_ids.clear()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _safe_after(self, delay_ms: int, callback) -> None:
        if self.closed:
            return
        try:
            after_id = self.root.after(delay_ms, callback)
            self._after_ids.add(after_id)
        except Exception:
            self.stop_event.set()
            self.closed = True

    def _amplitude_for_state(self) -> float:
        if self.state in (STATE_WAKE_DETECTED, STATE_LISTENING):
            return 24.0
        if self.state in (STATE_TRANSCRIBING, STATE_REPLYING):
            return 16.0
        if self.state == STATE_SPEAKING:
            return 22.0
        if self.state == STATE_ERROR:
            return 8.0
        return 8.0

    def _color_for_state(self) -> str:
        if self.state == STATE_ERROR:
            return "#ff6b6b"
        if self.state == STATE_RESULT:
            return "#6ee7b7"
        if self.state == STATE_SPEAKING:
            return "#a78bfa"
        if self.state == STATE_REPLYING:
            return "#facc15"
        if self.state == STATE_TRANSCRIBING:
            return "#facc15"
        if self.state in (STATE_WAKE_DETECTED, STATE_LISTENING):
            return "#38bdf8"
        return "#64748b"


def main() -> int:
    args = parse_args()
    config = load_config()
    app_config = load_user_config(args.config, warn=lambda msg: print(f"Config warning: {msg}"))
    app_config = apply_cli_overrides(app_config, args)
    debug = bool(app_config.runtime.debug)
    enable_llm = bool(app_config.llm.enabled)
    enable_tts = bool(app_config.tts.enabled)
    resident_hidden = bool(app_config.overlay.resident_hidden)
    logger = configure_logging(
        PROJECT_ROOT / config["logging"]["directory"],
        "voice_overlay",
        config["logging"]["level"],
    )

    try:
        import tkinter as tk
    except ImportError:
        print("Tkinter is not available in this Python environment.")
        return 2

    stop_event = threading.Event()
    root = tk.Tk()
    app = VoiceOverlayApp(
        root,
        stop_event=stop_event,
        debug=debug,
        start_hidden=resident_hidden,
        title=app_config.assistant.display_name,
        wake_phrase=app_config.wake.phrases[0] if app_config.wake.phrases else "小黄",
    )

    try:
        health = check_server_health(args.server_url)
    except (SttServerUnavailable, SttServerError) as exc:
        message = (
            f"{exc}\n"
            "请先运行 python scripts\\stt_server.py --host 127.0.0.1 --port 8766"
        )
        print(message)
        logger.error(str(exc))
        app.show_status(build_server_unavailable_status(args.server_url))
        root.mainloop()
        stop_event.set()
        return 6

    if debug:
        print(f"STT server ready: {args.server_url} ({health.get('status', 'ok')})")

    audio_config = config.get("audio", {})
    recording_config = config.get("recording", {})
    device_id = args.device
    if device_id is None:
        config_device = audio_config.get("device_id")
        device_id = int(config_device) if config_device is not None else 0
    recording_dir = PROJECT_ROOT / recording_config.get("output_dir", "data/recordings")
    wake_phrases = parse_wake_phrases(args.wake_phrases) if args.wake_phrases else app_config.wake.phrases
    wake_aliases = parse_wake_phrases(args.wake_aliases) if args.wake_aliases else app_config.wake.aliases
    options = WakeLoopOptions(
        device_id=device_id,
        server_url=args.server_url,
        wake_window_seconds=app_config.wake.wake_window_seconds,
        wake_phrases=wake_phrases,
        wake_aliases=wake_aliases,
        max_seconds=app_config.audio.max_seconds,
        silence_seconds=app_config.audio.silence_seconds,
        sample_rate=int(audio_config.get("sample_rate", 16000)),
        channels=int(audio_config.get("channels", 1)),
        recording_dir=recording_dir,
        keep_wake_recordings=False,
    )
    wake_engine_runtime = _build_wake_engine_runtime_config(app_config, options)
    wake_engine_plan = _select_wake_engine_runtime(wake_engine_runtime)
    if wake_engine_plan.error:
        print(wake_engine_plan.error)
        logger.error(wake_engine_plan.error)
        app.show_status(
            get_overlay_status_text(
                STATE_ERROR,
                wake_engine_plan.error,
                assistant_name=app.assistant_name,
                wake_phrase=app.wake_phrase,
            )
        )
        stop_event.set()
        return 7
    if wake_engine_plan.warning:
        print(wake_engine_plan.warning)
        logger.warning(wake_engine_plan.warning)
    _print_wake_engine_runtime_config(wake_engine_runtime, wake_engine_plan.engine, logger)

    tts_output_dir = PROJECT_ROOT / args.tts_output_dir
    post_response_cooldown = resolve_post_response_cooldown(enable_tts, app_config.overlay.post_response_cooldown)
    llm_config = load_llm_provider_config(app_config.llm)
    if enable_llm:
        if not llm_config.is_configured:
            if debug:
                print(f"LLM API key 未配置（{app_config.llm.api_key_env}），已使用本地规则回复")
            logger.info("--enable-llm specified but %s is not set; using local rule replies", app_config.llm.api_key_env)
        elif debug:
            print(f"LLM enabled: provider={llm_config.provider} model={llm_config.model} max_tokens={llm_config.max_tokens} timeout={llm_config.timeout_seconds}s")
    if debug:
        print(f"Resolved wake phrases: {wake_phrases}")
        print(f"Resolved wake aliases: {wake_aliases}")
        print(f"Wake engine: {wake_engine_plan.engine}")
        print(f"TTS enabled: {enable_tts}")
    session_config = ConversationSessionConfig(
        enabled=app_config.conversation.enabled,
        timeout_seconds=app_config.conversation.session_timeout,
        max_turns=app_config.conversation.max_turns,
        followup_timeout_seconds=app_config.conversation.followup_timeout,
        max_session_seconds=app_config.conversation.max_session_seconds,
        max_no_speech_retries=app_config.conversation.max_no_speech_retries,
    )
    if debug and session_config.enabled:
        _safe_print(
            f"Conversation session config: "
            f"followup_timeout={session_config.followup_timeout_seconds} "
            f"max_turns={session_config.max_turns} "
            f"max_session_seconds={session_config.max_session_seconds} "
            f"max_no_speech_retries={session_config.max_no_speech_retries}"
        )
    worker = threading.Thread(
        target=_run_overlay_loop,
        args=(
            app,
            options,
            logger,
            debug,
            stop_event,
            enable_tts,
            app_config.tts.voice,
            tts_output_dir,
            post_response_cooldown,
            enable_llm,
            llm_config,
            resident_hidden,
            session_config,
            app_config.assistant.persona,
            wake_engine_runtime,
            wake_engine_plan.engine,
        ),
        daemon=True,
    )
    worker.start()
    root.mainloop()
    stop_event.set()
    worker.join(timeout=1.0)
    return 0


def _run_overlay_loop(
    app: VoiceOverlayApp,
    options: WakeLoopOptions,
    logger,
    debug: bool,
    stop_event: threading.Event,
    enable_tts: bool,
    tts_voice: str,
    tts_output_dir: Path,
    post_response_cooldown: float,
    enable_llm: bool,
    llm_config,
    resident_hidden: bool = False,
    session_config: ConversationSessionConfig = ConversationSessionConfig(),
    persona: str | None = None,
    wake_engine_runtime: WakeEngineRuntimeConfig | None = None,
    wake_engine_mode: str = WAKE_ENGINE_STT_TEXT,
) -> None:
    def _overlay_stt(path, server_url, *, mode: str):
        try:
            return request_transcription(path, server_url)
        except (SttServerUnavailable, SttServerError) as exc:
            if mode == STT_MODE_WAKE_CHECK:
                if debug:
                    _safe_print(f"Wake check STT failed, skipped this window: {exc}")
                logger.warning("Wake check STT failed, skipped this window: %s", exc)
                return {"text": ""}
            raise

    def _run_stt_text_turn(turn_tracker: LatencyTracker) -> WakeLoopResult:
        on_wake_shown: Callable[[], None] | None = None
        if resident_hidden:
            on_wake_shown = lambda: (
                app.show_overlay(),
                app.thread_safe_set_state(STATE_WAKE_DETECTED),
            )
        return run_wake_loop_once(
            options,
            on_state_change=lambda state, payload=None: _handle_wake_state(app, state, payload),
            on_wake_text=(lambda text: _safe_print(f"Wake check transcription: {text}")) if debug else None,
            on_wake_match=(lambda match: _print_wake_match(match)) if debug else None,
            on_command_text=(lambda text: _safe_print(f"Command transcription: {text}")) if debug else None,
            on_wake_detected=on_wake_shown,
            request_transcription_func=_overlay_stt,
            latency_tracker=turn_tracker,
        )

    openwakeword_bridge: _OpenWakeWordBridgeRuntime | None = None
    openwakeword_listener: OpenWakeWordListenerHandle | None = None
    if wake_engine_mode == WAKE_ENGINE_OPENWAKEWORD and wake_engine_runtime is not None:
        openwakeword_bridge = _OpenWakeWordBridgeRuntime(wake_engine_runtime.cooldown_seconds)
        try:
            openwakeword_listener = _start_openwakeword_listener(
                app=app,
                runtime_config=wake_engine_runtime,
                bridge_runtime=openwakeword_bridge,
                logger=logger,
                debug=debug,
                stop_event=stop_event,
            )
        except WakeEngineRuntimeError as exc:
            if wake_engine_runtime.fallback_enabled:
                _log_runtime_message(logger, "warning", f"fallback_to_stt_text reason={exc}")
                wake_engine_mode = WAKE_ENGINE_STT_TEXT
            else:
                _log_runtime_message(logger, "error", f"openwakeword_listener_error error={exc}")
                app.thread_safe_set_state(STATE_ERROR, str(exc))
                return

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
                            debug=debug,
                            stop_event=stop_event,
                            latency_tracker=turn_tracker,
                            resident_hidden=resident_hidden,
                            request_transcription_func=_overlay_stt,
                        )
                    except WakeEngineLoopStopped:
                        break
                    except WakeEngineRuntimeError as exc:
                        _stop_openwakeword_listener(openwakeword_listener)
                        openwakeword_listener = None
                        if wake_engine_runtime.fallback_enabled:
                            wake_engine_mode = WAKE_ENGINE_STT_TEXT
                            result = _run_stt_text_turn(turn_tracker)
                        else:
                            app.thread_safe_set_state(STATE_ERROR, str(exc))
                            break
                else:
                    result = _run_stt_text_turn(turn_tracker)
                if stop_event.is_set():
                    break
                logger.info("Overlay command transcription: %s", result.command_text)
                app.thread_safe_set_state(STATE_REPLYING)

                pipeline_config = ReplyPipelineConfig(
                    enable_llm=enable_llm,
                    enable_tts=enable_tts,
                    llm_config=llm_config,
                    tts_voice=tts_voice,
                    tts_output_dir=tts_output_dir,
                    persona=persona,
                )
                pipeline_result = _generate_reply_pipeline_guarded(
                    result.command_text,
                    config=pipeline_config,
                    app=app,
                    bridge_runtime=openwakeword_bridge,
                    on_debug=_make_llm_debug_handler(logger, debug),
                    playback_warn=lambda message: _playback_warning(logger, message),
                    latency_tracker=turn_tracker,
                )

                if debug:
                    _safe_print(f"XiaoHuang reply: {pipeline_result.reply_text}")
                    _safe_print(f"Reply source: {pipeline_result.reply_source}")
                    turn_tracker.end("turn_total_ms")
                    summary = turn_tracker.summary_ms()
                    if summary:
                        _safe_print(format_latency_summary(summary, turn=1, source=pipeline_result.reply_source))
                turn_tracker.end("turn_total_ms")
                logger.info(format_latency_summary(turn_tracker.summary_ms(), turn=1, source=pipeline_result.reply_source))
                logger.info("Overlay reply: %s (source=%s)", pipeline_result.reply_text, pipeline_result.reply_source)

                if pipeline_result.tts_error:
                    _warn(logger, pipeline_result.tts_error)

                if session_config.enabled:
                    if stop_event.wait(0.3):
                        break
                    _session_callbacks = AssistantSessionCallbacks(
                        set_state=lambda s, d=None: app.thread_safe_set_state(s, d),
                        log_info=lambda msg: logger.info(msg),
                        wait_seconds=lambda s: stop_event.wait(s),
                        record_followup=lambda max_s, lt: _record_command_transcribe(
                            options=options,
                            max_seconds=max_s,
                            debug=debug,
                            logger=logger,
                            on_track_start=lambda name: _make_latency_track(lt)(name, start=True),
                            on_track_end=lambda name: _make_latency_track(lt)(name, start=False),
                        ),
                        generate_reply=lambda text, lt: _generate_reply_pipeline_guarded(
                            text,
                            config=pipeline_config,
                            app=app,
                            bridge_runtime=openwakeword_bridge,
                            on_debug=_make_llm_debug_handler(logger, debug),
                            playback_warn=lambda m: _playback_warning(logger, m),
                            latency_tracker=lt,
                        ),
                        debug_print=_safe_print if debug else None,
                        log_warning=lambda msg: _warn(logger, msg),
                        hide_overlay=app.hide_overlay if resident_hidden else None,
                    )
                    _session_outcome = run_session_followup_loop(
                        session_config=session_config,
                        callbacks=_session_callbacks,
                        session_start_time=time.perf_counter(),
                        enable_tts=enable_tts,
                        post_response_cooldown=post_response_cooldown,
                        debug=debug,
                    )
                    if not _session_outcome.should_continue_main_loop:
                        break
                else:
                    _callbacks = AssistantRuntimeCallbacks(
                        set_state=lambda s, d=None: app.thread_safe_set_state(s, d),
                        log_warn=lambda msg: _warn(logger, msg),
                        debug_print=_safe_print if debug else None,
                        wait=lambda s: stop_event.wait(s),
                        hide_overlay=app.hide_overlay if resident_hidden else None,
                    )
                    _outcome = handle_single_turn_reply_result(
                        callbacks=_callbacks,
                        pipeline_result=pipeline_result,
                        command_text=result.command_text,
                        assistant_name=app.assistant_name,
                        post_response_cooldown=post_response_cooldown,
                        resident_hidden=resident_hidden,
                    )
                    if not _outcome.continue_loop:
                        break
            except (SttServerUnavailable, SttServerError) as exc:
                if stop_event.is_set():
                    break
                logger.warning("Command STT failed: %s", exc)
                if debug:
                    _safe_print(f"Command STT failed: {exc}")
                app.thread_safe_set_state(STATE_ERROR, f"STT 转写失败：{exc}")
                if stop_event.wait(2.0):
                    break
            except Exception as exc:
                if stop_event.is_set():
                    break
                logger.exception("Voice overlay wake loop failed.")
                app.thread_safe_set_state(STATE_ERROR, str(exc))
                if stop_event.wait(2.0):
                    break
    finally:
        if openwakeword_listener is not None:
            _stop_openwakeword_listener(openwakeword_listener)


def _run_openwakeword_turn_from_listener(
    *,
    app: VoiceOverlayApp,
    options: WakeLoopOptions,
    listener: OpenWakeWordListenerHandle,
    logger,
    debug: bool,
    stop_event: threading.Event,
    latency_tracker=None,
    resident_hidden: bool = False,
    request_transcription_func: Callable[..., dict] = request_transcription,
    record_func=record_until_silence,
    build_recording_path_func=build_recording_path,
) -> WakeLoopResult:
    event = _wait_for_openwakeword_event(listener, stop_event)
    return _record_openwakeword_command(
        event=event,
        app=app,
        options=options,
        bridge_runtime=listener.bridge_runtime,
        logger=logger,
        debug=debug,
        latency_tracker=latency_tracker,
        resident_hidden=resident_hidden,
        request_transcription_func=request_transcription_func,
        record_func=record_func,
        build_recording_path_func=build_recording_path_func,
    )


def _record_openwakeword_command(
    *,
    event: WakeEvent,
    app: VoiceOverlayApp,
    options: WakeLoopOptions,
    bridge_runtime: _OpenWakeWordBridgeRuntime,
    logger,
    debug: bool,
    latency_tracker=None,
    resident_hidden: bool = False,
    request_transcription_func: Callable[..., dict] = request_transcription,
    record_func=record_until_silence,
    build_recording_path_func=build_recording_path,
) -> WakeLoopResult:
    _track = _make_latency_track(latency_tracker)
    if resident_hidden:
        app.show_overlay()
    app.thread_safe_set_state(STATE_WAKE_DETECTED, f"{event.wake_phrase} ({event.label})")
    _log_runtime_message(logger, "info", "command_record_start source=openwakeword")

    bridge_runtime.mark_command_started()
    try:
        app.thread_safe_set_state(STATE_LISTENING)
        app.thread_safe_set_state(STATE_TRANSCRIBING)
        result = record_and_transcribe(
            device_id=options.device_id,
            sample_rate=options.sample_rate,
            channels=options.channels,
            max_seconds=options.max_seconds,
            silence_seconds=options.silence_seconds,
            recording_dir=options.recording_dir,
            server_url=options.server_url,
            transcribe_func=request_transcription_func,
            record_func=record_func,
            build_recording_path_func=build_recording_path_func,
            stt_mode=STT_MODE_COMMAND,
            on_track_start=lambda name: _track(name, start=True),
            on_track_end=lambda name: _track(name, start=False),
        )
    finally:
        bridge_runtime.mark_command_finished()

    if debug:
        _safe_print(f"Command transcription: {result.command_text}")
    return WakeLoopResult(
        wake_text=event.label,
        command_text=result.command_text,
        command_path=result.command_path,
        actual_recording_seconds=result.actual_recording_seconds,
        stop_reason=result.stop_reason,
    )


def _run_openwakeword_wake_loop_once(
    *,
    app: VoiceOverlayApp,
    options: WakeLoopOptions,
    runtime_config: WakeEngineRuntimeConfig,
    bridge_runtime: _OpenWakeWordBridgeRuntime,
    logger,
    debug: bool,
    stop_event: threading.Event,
    latency_tracker=None,
    resident_hidden: bool = False,
    request_transcription_func: Callable[..., dict] = request_transcription,
    adapter_factory: Callable[[WakeEngineRuntimeConfig], object] | None = None,
    record_func=record_until_silence,
    build_recording_path_func=build_recording_path,
) -> WakeLoopResult:
    adapter = (adapter_factory or _create_openwakeword_adapter)(runtime_config)
    try:
        while not stop_event.is_set():
            app.thread_safe_set_state(STATE_WAKE_CHECKING, f"openWakeWord：{runtime_config.wake_phrase}")
            bridge_runtime.begin_wait(adapter)
            try:
                adapter.run_for_duration(
                    runtime_config.poll_seconds,
                    on_event=lambda event: _handle_openwakeword_event(event, bridge_runtime, logger, debug),
                    debug=debug,
                )
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                raise WakeEngineRuntimeError(_wake_engine_runtime_error(adapter, exc)) from exc
            finally:
                try:
                    adapter.stop()
                finally:
                    bridge_runtime.end_wait()
            event = bridge_runtime.accepted_event
            if event is None:
                continue

            return _record_openwakeword_command(
                event=event,
                app=app,
                options=options,
                bridge_runtime=bridge_runtime,
                logger=logger,
                debug=debug,
                latency_tracker=latency_tracker,
                resident_hidden=resident_hidden,
                request_transcription_func=request_transcription_func,
                record_func=record_func,
                build_recording_path_func=build_recording_path_func,
            )
    finally:
        _stop_adapter_safely(adapter)
    raise WakeEngineLoopStopped()


def _generate_reply_pipeline_guarded(
    command_text: str,
    *,
    config: ReplyPipelineConfig,
    app: VoiceOverlayApp,
    bridge_runtime: _OpenWakeWordBridgeRuntime | None,
    on_debug,
    playback_warn,
    latency_tracker,
) -> ReplyPipelineResult:

    def _before_tts(text: str) -> None:
        if bridge_runtime is not None:
            bridge_runtime.mark_tts_started()
        app.thread_safe_set_state(STATE_SPEAKING, text)

    def _after_tts() -> None:
        if bridge_runtime is not None:
            bridge_runtime.mark_tts_finished()

    return generate_reply_runtime_result(
        command_text,
        config=config,
        on_debug=on_debug,
        playback_warn=playback_warn,
        latency_tracker=latency_tracker,
        on_before_tts=_before_tts,
        on_after_tts=_after_tts,
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


def _safe_print(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _log_runtime_message(logger, level: str, message: str) -> None:
    _safe_print(message)
    log_func = getattr(logger, level, logger.info)
    log_func(message)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _handle_wake_state(app: VoiceOverlayApp, state: str, payload: str | None = None) -> None:
    if state == STATE_RESULT:
        return
    app.thread_safe_set_state(state, payload)


def _warn(logger, message: str) -> None:
    _safe_print(f"Warning: {message}")
    logger.warning(message)


def _playback_warning(logger, message: str) -> None:
    _safe_print(message)
    logger.warning(message)


def _print_wake_match(match: WakeMatchResult) -> None:
    detected = "true" if match.detected else "false"
    print(f"Wake match: detected={detected} score={match.score:.2f} reason={match.reason}")


def _make_llm_debug_handler(logger, debug_enabled: bool):
    if not debug_enabled:
        return None
    def _log(msg: str) -> None:
        try:
            print(f"DeepSeek debug: {msg}")
        except UnicodeEncodeError:
            encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
            print(f"DeepSeek debug: {msg}".encode(encoding, errors="replace").decode(encoding, errors="replace"))
        logger.info("DeepSeek debug: %s", msg)
    return _log


def _source_note_for_overlay(source: str) -> str | None:
    from xiaohuang.reply_pipeline_service import _source_note_for_source
    return _source_note_for_source(source)


if __name__ == "__main__":
    raise SystemExit(main())
