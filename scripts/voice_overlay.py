from __future__ import annotations

import argparse
import math
import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.config_service import load_config
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
from xiaohuang.reply_pipeline_service import ReplyPipelineConfig
from xiaohuang.overlay_loop_runtime_service import (
    OverlayLoopRuntimeConfig,
    run_overlay_runtime,
)
from xiaohuang.app_config_service import apply_cli_overrides, load_config as load_user_config
from xiaohuang.audio_capture_service import build_recording_path
from xiaohuang.command_runtime_service import record_and_transcribe
from xiaohuang.stt_client_service import SttServerError, SttServerUnavailable, check_server_health, request_transcription
from xiaohuang.tts_service import DEFAULT_TTS_VOICE
from xiaohuang.vad_recording_service import record_until_silence
from xiaohuang.wake_engine_service import WakeEvent
from xiaohuang.wake_loop_service import STT_MODE_COMMAND, WakeLoopOptions, WakeLoopResult
from xiaohuang.wake_runtime_service import (
    WAKE_ENGINE_OPENWAKEWORD,
    WAKE_ENGINE_STT_TEXT,
    WakeEngineRuntimeConfig,
    WakeEngineRuntimePlan,
    OpenWakeWordBridgeRuntime,
    OpenWakeWordBridgeRuntime as _OpenWakeWordBridgeRuntime,
    build_wake_engine_runtime_config as _build_wake_engine_runtime_config,
    select_wake_engine_runtime as _select_wake_engine_runtime,
)
from xiaohuang.wake_word_service import WakeMatchResult, parse_wake_phrases


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
    _W = 620
    _H = 110
    _BAR_COUNT = 18
    _BAR_W = 3
    _BAR_GAP = 4
    _ANIM_MS = 80

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
        self._title_text = ""
        self._sub_text = ""
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

    # ── UI construction ────────────────────────────────────────

    def _build_ui(self, title: str = "小黄") -> None:
        self.root.title(title)
        # Position bottom-center
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - self._W) // 2
        y = sh - self._H - 52
        self.root.geometry(f"{self._W}x{self._H}+{x}+{y}")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        try:
            self.root.overrideredirect(True)
        except Exception:
            pass
        self._tk = tk
        try:
            self.root.wm_attributes("-transparentcolor", "#010101")
        except Exception:
            pass
        self.canvas = self._tk.Canvas(
            self.root, width=self._W, height=self._H,
            bg="#010101", highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._start_move)
        self.canvas.bind("<B1-Motion>", self._move)
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
        except self._tk.TclError:
            pass

    # ── State management ───────────────────────────────────────

    def set_state(self, state: str, detail: str | None = None) -> None:
        if self.closed:
            return
        status = get_overlay_status_text(
            state, detail,
            assistant_name=self.assistant_name,
            wake_phrase=self.wake_phrase,
        )
        self.state = status.state
        self._title_text = status.title
        self._sub_text = status.subtitle

    def thread_safe_set_state(self, state: str, detail: str | None = None) -> None:
        self._safe_after(0, lambda: self.set_state(state, detail))

    def show_status(self, status) -> None:
        if self.closed:
            return
        self.state = status.state
        self._title_text = status.title
        self._sub_text = status.subtitle

    def thread_safe_show_status(self, status) -> None:
        self._safe_after(0, lambda: self.show_status(status))

    def schedule_idle(self, delay_ms: int = 3500) -> None:
        self._safe_after(delay_ms, lambda: self.set_state(STATE_IDLE))

    # ── Window visibility ──────────────────────────────────────

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

    # ── Animation loop ─────────────────────────────────────────

    def _animate(self) -> None:
        if self.closed:
            return
        try:
            self.canvas.delete("all")
        except self._tk.TclError:
            self.closed = True
            return
        self._draw_hud()
        self.phase += 0.22
        self._safe_after(self._ANIM_MS, self._animate)

    # ── HUD drawing ────────────────────────────────────────────

    def _draw_hud(self) -> None:
        c = self._palette()
        margin = 6
        x0, y0 = margin, margin
        x1, y1 = self._W - margin, self._H - margin
        r = 18
        # Semi-transparent backdrop capsule
        self._rounded_rect(x0, y0, x1, y1, r, fill="#080e14", outline=c["primary"])
        cy = self._H // 2

        # ── Left: status dot + text ──
        dot_x, dot_y = 28, cy
        self.canvas.create_oval(dot_x - 4, dot_y - 4, dot_x + 4, dot_y + 4,
                                fill=c["accent"], outline=c["primary"], width=1)
        self.canvas.create_text(
            dot_x + 18, cy - 10,
            text=self._title_text, fill=c["primary"],
            font=("Microsoft YaHei UI", 15, "bold"), anchor="w",
        )
        self.canvas.create_text(
            dot_x + 18, cy + 12,
            text=self._sub_text, fill=c["secondary"],
            font=("Microsoft YaHei UI", 10), anchor="w",
        )

        # ── Center: horizontal waveform ──
        self._draw_waveform(c["primary"])

        # ── Right: corner ornament ──
        rx1, rx2 = x1 - r - 6, x1 - r + 10
        self.canvas.create_line(rx1, y0 + r, rx2, y0 + r, fill=c["primary"], width=1)
        self.canvas.create_line(rx1, y0 + r + 4, rx2, y0 + r + 4, fill=c["primary"], width=1)

    # ── Waveform ───────────────────────────────────────────────

    def _draw_waveform(self, color: str) -> None:
        amp = self._amplitude_for_state()
        n = self._BAR_COUNT
        total_w = n * (self._BAR_W + self._BAR_GAP) - self._BAR_GAP
        cx = self._W // 2
        cy = self._H // 2
        x0 = cx - total_w // 2
        for i in range(n):
            offset = 0.28 + 0.72 * abs(math.sin(self.phase * 1.9 + i * 0.52))
            h = max(3, 4 + amp * offset)
            x = x0 + i * (self._BAR_W + self._BAR_GAP)
            y1 = int(cy - h / 2)
            y2 = int(cy + h / 2)
            self.canvas.create_rectangle(
                x, y1, x + self._BAR_W, y2, fill=color, outline="",
            )

    # ── Palette ────────────────────────────────────────────────

    def _palette(self) -> dict:
        s = self.state
        if s == STATE_ERROR:
            return {"primary": "#ff5252", "secondary": "#ff8a80", "accent": "#ff1744"}
        if s == STATE_SPEAKING:
            return {"primary": "#b388ff", "secondary": "#7c4dff", "accent": "#e040fb"}
        if s == STATE_REPLYING:
            return {"primary": "#448aff", "secondary": "#82b1ff", "accent": "#2962ff"}
        if s == STATE_TRANSCRIBING:
            return {"primary": "#18ffff", "secondary": "#00b8d4", "accent": "#7c4dff"}
        if s == STATE_RESULT:
            return {"primary": "#00e676", "secondary": "#69f0ae", "accent": "#00c853"}
        if s in (STATE_WAKE_DETECTED, STATE_LISTENING):
            return {"primary": "#00e5ff", "secondary": "#18ffff", "accent": "#00e676"}
        if s == STATE_WAKE_CHECKING:
            return {"primary": "#40c4ff", "secondary": "#80deea", "accent": "#00b0ff"}
        # idle default
        return {"primary": "#4dd0e1", "secondary": "#80cbc4", "accent": "#00bcd4"}

    def _amplitude_for_state(self) -> float:
        s = self.state
        if s in (STATE_WAKE_DETECTED, STATE_LISTENING):
            return 32.0
        if s == STATE_SPEAKING:
            return 28.0
        if s in (STATE_TRANSCRIBING, STATE_REPLYING):
            return 20.0
        if s == STATE_ERROR:
            return 14.0
        if s == STATE_WAKE_CHECKING:
            return 8.0
        return 7.0

    # ── Drawing helpers ────────────────────────────────────────

    def _rounded_rect(self, x0: int, y0: int, x1: int, y1: int, r: int,
                      *, fill: str = "", outline: str = "") -> None:
        d = r * 2
        c = self.canvas
        for sx, sy in [(x0, y0), (x1 - d, y0), (x1 - d, y1 - d), (x0, y1 - d)]:
            c.create_arc(sx, sy, sx + d, sy + d, start=90, extent=90,
                         style="arc" if not fill else "pieslice",
                         outline=outline, fill=fill if fill else "", width=1)
        c.create_line(x0 + r, y0, x1 - r, y0, fill=outline, width=1)
        c.create_line(x0 + r, y1, x1 - r, y1, fill=outline, width=1)
        c.create_line(x0, y0 + r, x0, y1 - r, fill=outline, width=1)
        c.create_line(x1, y0 + r, x1, y1 - r, fill=outline, width=1)
        if fill:
            c.create_rectangle(x0 + r, y0 + 1, x1 - r + 1, y1, fill=fill, outline="")
            c.create_rectangle(x0 + 1, y0 + r, x1 + 1, y1 - r + 1, fill=fill, outline="")

    # ── Lifecycle ──────────────────────────────────────────────

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
        def _wrapper() -> None:
            self._after_ids.discard(after_id)
            callback()
        try:
            after_id = self.root.after(delay_ms, _wrapper)
            self._after_ids.add(after_id)
        except Exception:
            self.stop_event.set()
            self.closed = True


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
    pipeline_config = ReplyPipelineConfig(
        enable_llm=enable_llm,
        enable_tts=enable_tts,
        llm_config=llm_config,
        tts_voice=app_config.tts.voice,
        tts_output_dir=tts_output_dir,
        persona=app_config.assistant.persona,
    )

    runtime_config = OverlayLoopRuntimeConfig(
        wake_engine_mode=wake_engine_plan.engine,
        wake_engine_runtime=wake_engine_runtime,
        session_config=session_config,
        enable_tts=enable_tts,
        enable_llm=enable_llm,
        post_response_cooldown=post_response_cooldown,
        resident_hidden=resident_hidden,
        debug=debug,
        assistant_name=app.assistant_name,
    )

    worker = threading.Thread(
        target=run_overlay_runtime,
        kwargs={
            "app": app,
            "stop_event": stop_event,
            "logger": logger,
            "options": options,
            "runtime_config": runtime_config,
            "pipeline_config": pipeline_config,
            "record_openwakeword_command": _record_openwakeword_command,
            "make_llm_debug_handler": _make_llm_debug_handler,
            "playback_warning": _playback_warning,
            "log_warning": lambda msg: _warn(logger, msg),
            "print_wake_match": (_print_wake_match if debug else None),
        },
        daemon=True,
    )
    worker.start()
    root.mainloop()
    stop_event.set()
    worker.join(timeout=1.0)
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
