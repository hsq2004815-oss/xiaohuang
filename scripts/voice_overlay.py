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
from xiaohuang.conversation_session_service import (
    SESSION_EXIT_REPLY,
    ConversationSessionConfig,
    get_followup_timeout_seconds,
    get_session_end_reason,
    is_session_exit_text,
    should_continue_session,
    should_exit_for_no_speech,
)
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
from xiaohuang.openwakeword_adapter import (
    OpenWakeWordAdapter,
    OpenWakeWordDependencyStatus,
    OpenWakeWordRuntimeStatus,
    check_openwakeword_dependencies,
)
from xiaohuang.reply_pipeline_service import (
    ReplyPipelineConfig,
    ReplyPipelineResult,
    generate_reply_pipeline_result,
)
from xiaohuang.app_config_service import apply_cli_overrides, load_config as load_user_config
from xiaohuang.audio_capture_service import build_recording_path
from xiaohuang.stt_client_service import SttServerError, SttServerUnavailable, check_server_health, request_transcription
from xiaohuang.tts_service import DEFAULT_TTS_VOICE
from xiaohuang.vad_recording_service import record_until_silence
from xiaohuang.wake_command_bridge_service import WakeCommandBridge, WakeCommandBridgeConfig
from xiaohuang.wake_engine_service import WakeEvent
from xiaohuang.wake_loop_service import STT_MODE_COMMAND, STT_MODE_WAKE_CHECK, WakeLoopOptions, WakeLoopResult, run_wake_loop_once
from xiaohuang.wake_word_service import DEFAULT_WAKE_ALIASES, WakeMatchResult, parse_wake_phrases


WAKE_ENGINE_STT_TEXT = "stt_text"
WAKE_ENGINE_OPENWAKEWORD = "openwakeword"
OPENWAKEWORD_POLL_SECONDS = 1.0
OPENWAKEWORD_QUEUE_POLL_SECONDS = 0.1
OPENWAKEWORD_STATUS_INTERVAL_SECONDS = 5.0


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


@dataclass(frozen=True)
class WakeEngineRuntimeConfig:
    engine: str
    wake_phrase: str
    fallback_enabled: bool
    device: int | None
    sample_rate: int
    sensitivity: float
    cooldown_seconds: float
    model_path: str | None
    model_name: str | None
    poll_seconds: float = OPENWAKEWORD_POLL_SECONDS


@dataclass(frozen=True)
class WakeEngineRuntimePlan:
    engine: str
    warning: str | None = None
    error: str | None = None
    dependency_status: OpenWakeWordDependencyStatus | None = None


class WakeEngineLoopStopped(Exception):
    pass


class WakeEngineRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenWakeWordListenerHandle:
    thread: threading.Thread
    adapter: object
    event_queue: queue.Queue[WakeEvent]
    error_queue: queue.Queue[str]
    bridge_runtime: "_OpenWakeWordBridgeRuntime"


class _OpenWakeWordBridgeRuntime:
    def __init__(
        self,
        cooldown_seconds: float,
        command_queue: queue.Queue[WakeEvent] | None = None,
    ) -> None:
        self.accepted_event: WakeEvent | None = None
        self.active_adapter = None
        self.command_queue = command_queue
        self._lock = threading.RLock()
        self.bridge = WakeCommandBridge(
            WakeCommandBridgeConfig(post_wake_cooldown_seconds=cooldown_seconds),
            self._accept_wake_event,
        )

    def begin_wait(self, adapter) -> None:
        with self._lock:
            self.accepted_event = None
            self.active_adapter = adapter

    def end_wait(self) -> None:
        with self._lock:
            self.active_adapter = None

    def handle_event(self, event: WakeEvent):
        with self._lock:
            return self.bridge.handle_wake_event(event)

    def mark_command_started(self) -> None:
        with self._lock:
            self.bridge.mark_command_started()

    def mark_command_finished(self) -> None:
        with self._lock:
            self.bridge.mark_command_finished()

    def mark_tts_started(self) -> None:
        with self._lock:
            self.bridge.mark_tts_started()

    def mark_tts_finished(self) -> None:
        with self._lock:
            self.bridge.mark_tts_finished()

    def state(self):
        with self._lock:
            return self.bridge.state()

    def _accept_wake_event(self, event: WakeEvent) -> object:
        command_queue = None
        with self._lock:
            self.accepted_event = event
            self.bridge.mark_command_started()
            command_queue = self.command_queue
        if command_queue is not None:
            command_queue.put(event)
        return {"accepted": True}


def _build_wake_engine_runtime_config(app_config, options: WakeLoopOptions) -> WakeEngineRuntimeConfig:
    wake_phrase = app_config.wake.phrases[0] if app_config.wake.phrases else "小黄"
    wake_device = app_config.wake.device_index if app_config.wake.device_index is not None else options.device_id
    return WakeEngineRuntimeConfig(
        engine=_normalize_wake_engine(app_config.wake.engine),
        wake_phrase=wake_phrase,
        fallback_enabled=bool(app_config.wake.fallback_enabled),
        device=wake_device,
        sample_rate=options.sample_rate,
        sensitivity=float(app_config.wake.sensitivity),
        cooldown_seconds=float(app_config.wake.cooldown_seconds),
        model_path=app_config.wake.model_path,
        model_name=app_config.wake.model_name,
        poll_seconds=max(0.1, min(float(app_config.wake.wake_window_seconds), OPENWAKEWORD_POLL_SECONDS)),
    )


def _select_wake_engine_runtime(
    runtime_config: WakeEngineRuntimeConfig,
    *,
    dependency_status: OpenWakeWordDependencyStatus | None = None,
) -> WakeEngineRuntimePlan:
    engine = _normalize_wake_engine(runtime_config.engine)
    if engine == WAKE_ENGINE_STT_TEXT:
        return WakeEngineRuntimePlan(engine=WAKE_ENGINE_STT_TEXT)

    if engine != WAKE_ENGINE_OPENWAKEWORD:
        message = f"Unsupported wake.engine={runtime_config.engine!r}"
        if runtime_config.fallback_enabled:
            return WakeEngineRuntimePlan(
                engine=WAKE_ENGINE_STT_TEXT,
                warning=f"{message}; falling back to stt_text",
            )
        return WakeEngineRuntimePlan(engine=engine, error=message)

    status = dependency_status or check_openwakeword_dependencies()
    if status.ready_for_realtime_demo:
        return WakeEngineRuntimePlan(engine=WAKE_ENGINE_OPENWAKEWORD, dependency_status=status)

    message = _format_openwakeword_dependency_error(status)
    if runtime_config.fallback_enabled:
        return WakeEngineRuntimePlan(
            engine=WAKE_ENGINE_STT_TEXT,
            warning=f"{message}; falling back to stt_text",
            dependency_status=status,
        )
    return WakeEngineRuntimePlan(
        engine=WAKE_ENGINE_OPENWAKEWORD,
        error=message,
        dependency_status=status,
    )


def _normalize_wake_engine(engine: str | None) -> str:
    text = str(engine or WAKE_ENGINE_STT_TEXT).strip().lower().replace("-", "_")
    return text or WAKE_ENGINE_STT_TEXT


def _format_openwakeword_dependency_error(status: OpenWakeWordDependencyStatus) -> str:
    details = "; ".join(status.errors) if status.errors else "dependency check failed"
    return f"openwakeword dependency unavailable: {details}"


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


def _create_openwakeword_adapter(runtime_config: WakeEngineRuntimeConfig) -> OpenWakeWordAdapter:
    return OpenWakeWordAdapter(
        wake_phrase=runtime_config.wake_phrase,
        model_path=runtime_config.model_path,
        model_name=runtime_config.model_name,
        device=runtime_config.device,
        sample_rate=runtime_config.sample_rate,
        sensitivity=runtime_config.sensitivity,
        cooldown_seconds=runtime_config.cooldown_seconds,
    )


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
                    if not session_config.enabled:
                        app.thread_safe_set_state(STATE_ERROR, pipeline_result.tts_error)

                if session_config.enabled:
                    if stop_event.wait(0.3):
                        break
                else:
                    app.thread_safe_set_state(
                        STATE_RESULT,
                        build_reply_result_text(
                            result.command_text,
                            pipeline_result.reply_text,
                            pipeline_result.source_note,
                            assistant_name=app.assistant_name,
                        ),
                    )
                    if pipeline_result.tts_error:
                        _warn(logger, pipeline_result.tts_error)
                        app.thread_safe_set_state(STATE_ERROR, pipeline_result.tts_error)
                    if debug and post_response_cooldown > 0:
                        _safe_print(f"Post-response cooldown: {post_response_cooldown:.1f}s")
                    if stop_event.wait(post_response_cooldown):
                        break

                # --- conversation session: listen for follow-up commands ---
                turn_count = 1
                session_started = time.perf_counter()
                no_speech_retries = 0
                exit_phrase_detected = False
                while (
                    should_continue_session(
                        turn_count, session_config,
                        elapsed_seconds=time.perf_counter() - session_started,
                        no_speech_retries=no_speech_retries,
                    )
                    and not stop_event.is_set()
                ):
                    followup_timeout = get_followup_timeout_seconds(session_config)
                    st = LatencyTracker()
                    st.start("turn_total_ms")
                    if debug:
                        _safe_print(f"Session turn {turn_count + 1}/{session_config.max_turns} (follow-up window: {followup_timeout:.1f}s)")
                    app.thread_safe_set_state(STATE_LISTENING, "你还可以继续说")

                    next_text = _record_command_transcribe(
                        options=options,
                        max_seconds=followup_timeout,
                        stt_mode=STT_MODE_COMMAND,
                        debug=debug,
                        logger=logger,
                        latency_tracker=st,
                    )
                    if stop_event.is_set():
                        break
                    if not next_text:
                        no_speech_retries += 1
                        if debug:
                            _safe_print(f"Session no speech retry {no_speech_retries}/{session_config.max_no_speech_retries + 1}")
                        if should_exit_for_no_speech(no_speech_retries, session_config):
                            logger.info("Session ended: no_speech")
                            break
                        continue
                    if debug:
                        _safe_print(f"Session command: {next_text}")

                    no_speech_retries = 0

                    if is_session_exit_text(next_text):
                        if debug:
                            _safe_print("Session exit phrase detected")
                        pipeline_result = ReplyPipelineResult(
                            reply_text=SESSION_EXIT_REPLY, reply_source="session_exit", source_note=None,
                        )
                        if enable_tts and not stop_event.is_set():
                            pipeline_result = _generate_reply_pipeline_guarded(
                                next_text, config=pipeline_config,
                                app=app,
                                bridge_runtime=openwakeword_bridge,
                                on_debug=_make_llm_debug_handler(logger, debug),
                                playback_warn=lambda m: _playback_warning(logger, m),
                                latency_tracker=st,
                            )
                        _safe_print(f"XiaoHuang: {pipeline_result.reply_text}")
                        logger.info("Overlay reply: %s (source=%s)", pipeline_result.reply_text, pipeline_result.reply_source)
                        st.end("turn_total_ms")
                        logger.info(format_latency_summary(st.summary_ms(), turn=turn_count + 1, source=pipeline_result.reply_source))
                        app.thread_safe_set_state(
                            STATE_RESULT,
                            build_reply_result_text(
                                next_text,
                                pipeline_result.reply_text,
                                pipeline_result.source_note,
                                assistant_name=app.assistant_name,
                            ),
                        )
                        exit_phrase_detected = True
                        turn_count += 1
                        if stop_event.wait(post_response_cooldown):
                            break
                        break

                    pipeline_result = _generate_reply_pipeline_guarded(
                        next_text, config=pipeline_config,
                        app=app,
                        bridge_runtime=openwakeword_bridge,
                        on_debug=_make_llm_debug_handler(logger, debug),
                        playback_warn=lambda m: _playback_warning(logger, m),
                        latency_tracker=st,
                    )
                    _safe_print(f"XiaoHuang reply: {pipeline_result.reply_text}")
                    _safe_print(f"Reply source: {pipeline_result.reply_source}")
                    st.end("turn_total_ms")
                    logger.info(format_latency_summary(st.summary_ms(), turn=turn_count + 1, source=pipeline_result.reply_source))
                    logger.info("Overlay reply: %s (source=%s)", pipeline_result.reply_text, pipeline_result.reply_source)
                    if pipeline_result.tts_error:
                        _warn(logger, pipeline_result.tts_error)
                    if stop_event.wait(0.3):
                        break
                    turn_count += 1

                # --- end session, return to standby ---
                reason = get_session_end_reason(
                    turn_count=turn_count, config=session_config,
                    elapsed_seconds=time.perf_counter() - session_started,
                    no_speech_retries=no_speech_retries,
                    exit_phrase_detected=exit_phrase_detected,
                    stop_event_set=stop_event.is_set(),
                )
                if reason:
                    logger.info(
                        "Session ended: reason=%s completed_turns=%s max_turns=%s elapsed_seconds=%.1f "
                        "max_session_seconds=%.1f no_speech_retries=%s max_no_speech_retries=%s",
                        reason, turn_count, session_config.max_turns,
                        time.perf_counter() - session_started, session_config.max_session_seconds,
                        no_speech_retries, session_config.max_no_speech_retries,
                    )
                if stop_event.wait(0.5 if post_response_cooldown > 0 else 0):
                    break
                app.thread_safe_set_state(STATE_IDLE)
                if resident_hidden:
                    app.hide_overlay()
                stop_event.wait(0.5)
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


def _start_openwakeword_listener(
    *,
    app: VoiceOverlayApp,
    runtime_config: WakeEngineRuntimeConfig,
    bridge_runtime: _OpenWakeWordBridgeRuntime,
    logger,
    debug: bool,
    stop_event: threading.Event,
    adapter_factory: Callable[[WakeEngineRuntimeConfig], object] | None = None,
) -> OpenWakeWordListenerHandle:
    event_queue: queue.Queue[WakeEvent] = queue.Queue()
    error_queue: queue.Queue[str] = queue.Queue()
    bridge_runtime.command_queue = event_queue
    try:
        adapter = (adapter_factory or _create_openwakeword_adapter)(runtime_config)
    except Exception as exc:
        error = str(exc)
        _log_runtime_message(logger, "error", f"openwakeword_listener_error error={error}")
        raise WakeEngineRuntimeError(error) from exc

    handle = OpenWakeWordListenerHandle(
        thread=threading.Thread(
            target=_run_openwakeword_listener,
            kwargs={
                "app": app,
                "runtime_config": runtime_config,
                "bridge_runtime": bridge_runtime,
                "logger": logger,
                "debug": debug,
                "stop_event": stop_event,
                "adapter": adapter,
                "error_queue": error_queue,
            },
            name="openwakeword-listener",
            daemon=True,
        ),
        adapter=adapter,
        event_queue=event_queue,
        error_queue=error_queue,
        bridge_runtime=bridge_runtime,
    )
    handle.thread.start()
    return handle


def _run_openwakeword_listener(
    *,
    app: VoiceOverlayApp,
    runtime_config: WakeEngineRuntimeConfig,
    bridge_runtime: _OpenWakeWordBridgeRuntime,
    logger,
    debug: bool,
    stop_event: threading.Event,
    adapter,
    error_queue: queue.Queue[str],
) -> None:
    _log_runtime_message(logger, "info", "openwakeword_listener_starting")
    try:
        _log_runtime_message(logger, "info", "openwakeword_listener_running")
        app.thread_safe_set_state(STATE_WAKE_CHECKING, f"openWakeWord：{runtime_config.wake_phrase}")
        bridge_runtime.begin_wait(adapter)
        try:
            adapter.run_until_stopped(
                stop_event,
                on_event=lambda event: _handle_openwakeword_event(event, bridge_runtime, logger, debug),
                debug=debug,
                on_status=lambda status: _log_openwakeword_listener_status(logger, status),
                status_interval_seconds=OPENWAKEWORD_STATUS_INTERVAL_SECONDS,
            )
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            error = _wake_engine_runtime_error(adapter, exc)
            _log_runtime_message(logger, "error", f"openwakeword_listener_error error={error}")
            error_queue.put(error)
            if runtime_config.fallback_enabled:
                _log_runtime_message(logger, "warning", f"fallback_to_stt_text reason={error}")
            else:
                stop_event.set()
            return
        finally:
            bridge_runtime.end_wait()
    finally:
        _stop_adapter_safely(adapter)
        _log_runtime_message(logger, "info", "openwakeword_listener_stopped")


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


def _wait_for_openwakeword_event(
    listener: OpenWakeWordListenerHandle,
    stop_event: threading.Event,
) -> WakeEvent:
    while True:
        try:
            error = listener.error_queue.get_nowait()
        except queue.Empty:
            error = None
        if error is not None:
            raise WakeEngineRuntimeError(error)

        if stop_event.is_set():
            raise WakeEngineLoopStopped()

        try:
            return listener.event_queue.get(timeout=OPENWAKEWORD_QUEUE_POLL_SECONDS)
        except queue.Empty:
            pass

        if not listener.thread.is_alive():
            try:
                error = listener.error_queue.get_nowait()
            except queue.Empty:
                error = "openwakeword listener stopped unexpectedly"
            raise WakeEngineRuntimeError(error)


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
        command_path = build_recording_path_func(options.recording_dir)
        _track("command_record_ms", start=True)
        command_result = record_func(
            command_path,
            device_id=options.device_id,
            sample_rate=options.sample_rate,
            channels=options.channels,
            max_seconds=options.max_seconds,
            silence_seconds=options.silence_seconds,
        )
        _track("command_record_ms", start=False)
        app.thread_safe_set_state(STATE_TRANSCRIBING)
        _track("command_stt_ms", start=True)
        command_response = _call_overlay_transcription(
            request_transcription_func,
            command_result.path,
            options.server_url,
            STT_MODE_COMMAND,
        )
        _track("command_stt_ms", start=False)
    finally:
        bridge_runtime.mark_command_finished()

    command_text = str(command_response.get("text", ""))
    if debug:
        _safe_print(f"Command transcription: {command_text}")
    return WakeLoopResult(
        wake_text=event.label,
        command_text=command_text,
        command_path=Path(command_result.path),
        actual_recording_seconds=float(command_result.duration_seconds),
        stop_reason=str(command_result.stop_reason),
    )


def _stop_openwakeword_listener(listener: OpenWakeWordListenerHandle) -> None:
    _stop_adapter_safely(listener.adapter)
    listener.thread.join(timeout=1.0)


def _stop_adapter_safely(adapter) -> None:
    if adapter is None:
        return
    try:
        adapter.stop()
    except Exception:
        pass


def _log_openwakeword_listener_status(logger, status: OpenWakeWordRuntimeStatus) -> None:
    labels = ",".join(status.model_labels) if status.model_labels else "-"
    max_label = status.max_label or "-"
    max_score = "-" if status.max_score is None else f"{status.max_score:.3f}"
    _log_runtime_message(
        logger,
        "info",
        "openwakeword_listener_status "
        f"device_index={status.device} sample_rate={status.sample_rate} "
        f"sensitivity={status.sensitivity} model_labels={labels} "
        f"frames={status.frames_read} max_label={max_label} max_score={max_score} "
        f"raw={status.raw_detections} coalesced={status.coalesced_events} "
        f"suppressed={status.suppressed_detections}",
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


def _handle_openwakeword_event(
    event: WakeEvent,
    bridge_runtime: _OpenWakeWordBridgeRuntime,
    logger,
    debug: bool,
) -> None:
    _log_runtime_message(
        logger,
        "info",
        f"openwakeword_wake_event label={event.label} score={event.score}",
    )
    decision = bridge_runtime.handle_event(event)
    _log_runtime_message(
        logger,
        "info",
        "openwakeword_bridge_decision "
        f"accepted={_bool_text(decision.accepted)} reason={decision.reason}",
    )
    if debug:
        _safe_print(
            "openWakeWord event "
            f"label={event.label} score={event.score} "
            f"accepted={'true' if decision.accepted else 'false'} "
            f"reason={decision.reason}"
        )
    if not decision.accepted:
        logger.info("openWakeWord wake event suppressed: reason=%s label=%s", decision.reason, event.label)


def _wake_engine_runtime_error(adapter, exc: Exception) -> str:
    try:
        status = adapter.status()
    except Exception:
        status = None
    status_error = getattr(status, "error", None)
    return str(status_error or exc)


def _call_overlay_transcription(func: Callable[..., dict], wav_path: Path, server_url: str, mode: str) -> dict:
    try:
        return func(wav_path, server_url, mode=mode)
    except TypeError:
        return func(wav_path, server_url)


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
    tts_started = False

    def _on_before_tts(text: str) -> None:
        nonlocal tts_started
        tts_started = True
        if bridge_runtime is not None:
            bridge_runtime.mark_tts_started()
        app.thread_safe_set_state(STATE_SPEAKING, text)

    try:
        return generate_reply_pipeline_result(
            command_text,
            config=config,
            on_debug=on_debug,
            on_before_tts=_on_before_tts,
            playback_warn=playback_warn,
            latency_tracker=latency_tracker,
        )
    finally:
        if tts_started and bridge_runtime is not None:
            bridge_runtime.mark_tts_finished()


def _record_command_transcribe(
    *,
    options,
    max_seconds: float,
    stt_mode: str,
    debug: bool,
    logger,
    record_func=record_until_silence,
    transcribe_func=request_transcription,
    latency_tracker=None,
) -> str:
    _track = _make_latency_track(latency_tracker)
    try:
        cmd_path = build_recording_path(options.recording_dir)
        _track("command_record_ms", start=True)
        cmd_result = record_func(
            cmd_path,
            device_id=options.device_id,
            sample_rate=options.sample_rate,
            channels=options.channels,
            max_seconds=max_seconds,
            silence_seconds=options.silence_seconds,
        )
        _track("command_record_ms", start=False)
        _track("command_stt_ms", start=True)
        cmd_response = transcribe_func(cmd_result.path, options.server_url)
        _track("command_stt_ms", start=False)
        return str(cmd_response.get("text", ""))
    except (SttServerUnavailable, SttServerError) as exc:
        if debug:
            _safe_print(f"Session command STT failed: {exc}")
        logger.warning("Session command STT failed: %s", exc)
        return ""
    except Exception as exc:
        logger.warning("Session command recording failed: %s", exc)
        return ""


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
