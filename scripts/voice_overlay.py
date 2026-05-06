from __future__ import annotations

import argparse
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


_TCOLOR = "#010101"  # transparentcolor key

_STATE_COLORS = {
    STATE_IDLE:           (0x4a, 0x9e, 0xff),
    STATE_WAKE_CHECKING:  (0x3d, 0x8b, 0xfd),
    STATE_WAKE_DETECTED:  (0x00, 0xe5, 0xa0),
    STATE_LISTENING:      (0x00, 0xe5, 0xa0),
    STATE_TRANSCRIBING:   (0x7c, 0x6f, 0xff),
    STATE_REPLYING:       (0x00, 0xb4, 0xff),
    STATE_SPEAKING:       (0x9b, 0x6d, 0xff),
    STATE_RESULT:         (0x00, 0xd6, 0x8f),
    STATE_ERROR:          (0xff, 0x47, 0x57),
}

_STATE_AMPS = {
    STATE_IDLE: 3.2, STATE_WAKE_CHECKING: 5.5,
    STATE_WAKE_DETECTED: 13, STATE_LISTENING: 15,
    STATE_TRANSCRIBING: 8, STATE_REPLYING: 9,
    STATE_SPEAKING: 20, STATE_RESULT: 4.5,
    STATE_ERROR: 12,
}

_STATE_SPEEDS = {
    STATE_IDLE: 0.65, STATE_WAKE_CHECKING: 1.1,
    STATE_WAKE_DETECTED: 1.5, STATE_LISTENING: 1.65,
    STATE_TRANSCRIBING: 1.2, STATE_REPLYING: 1.15,
    STATE_SPEAKING: 1.9, STATE_RESULT: 0.75,
    STATE_ERROR: 3.5,
}


class VoiceOverlayApp:
    """Tkinter transparent Canvas waveform dock.

    Renders a multi-layer sin-wave voice HUD using only
    Canvas create_line.  Background is keyed out via
    wm_attributes -transparentcolor so the desktop shows
    through everywhere except the waveform lines.
    """

    _W = 720
    _H = 160
    _ANIM_MS = 70
    _LAYERS = 4
    _STEP = 3  # px between waveform sample points

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
        self.closed = False
        self._resident_hidden = start_hidden
        self._after_ids: set[str] = set()

        # live interpolation targets
        self._live_amp = 0.0
        self._live_spd = _STATE_SPEEDS[STATE_IDLE]
        self._live_r, self._live_g, self._live_b = _STATE_COLORS[STATE_IDLE]
        self._tgt_r, self._tgt_g, self._tgt_b = self._live_r, self._live_g, self._live_b
        self._tgt_amp = _STATE_AMPS[STATE_IDLE]
        self._tgt_spd = _STATE_SPEEDS[STATE_IDLE]
        self._flash = 0.0
        self._time = 0.0
        self._last_ts = 0.0

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
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - self._W) // 2
        y = sh - self._H - 44
        self.root.geometry(f"{self._W}x{self._H}+{x}+{y}")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        try:
            self.root.overrideredirect(True)
        except Exception:
            pass
        try:
            self.root.wm_attributes("-transparentcolor", _TCOLOR)
        except Exception:
            pass
        self.canvas = tk.Canvas(
            self.root, width=self._W, height=self._H,
            bg=_TCOLOR, highlightthickness=0, bd=0,
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
        except tk.TclError:
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
        s = status.state
        if s == self.state:
            return
        self.state = s
        rgb = _STATE_COLORS.get(s, _STATE_COLORS[STATE_IDLE])
        self._tgt_r, self._tgt_g, self._tgt_b = rgb
        self._tgt_amp = _STATE_AMPS.get(s, _STATE_AMPS[STATE_IDLE])
        self._tgt_spd = _STATE_SPEEDS.get(s, _STATE_SPEEDS[STATE_IDLE])
        self._flash = 0.22

    def thread_safe_set_state(self, state: str, detail: str | None = None) -> None:
        self._safe_after(0, lambda: self.set_state(state, detail))

    def show_status(self, status) -> None:
        if self.closed:
            return
        self.state = status.state
        rgb = _STATE_COLORS.get(status.state, _STATE_COLORS[STATE_IDLE])
        self._tgt_r, self._tgt_g, self._tgt_b = rgb
        self._tgt_amp = _STATE_AMPS.get(status.state, _STATE_AMPS[STATE_IDLE])
        self._tgt_spd = _STATE_SPEEDS.get(status.state, _STATE_SPEEDS[STATE_IDLE])

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

    # ── Animation ──────────────────────────────────────────────

    def _animate(self) -> None:
        if self.closed:
            return
        try:
            self.canvas.delete("all")
        except tk.TclError:
            self.closed = True
            return
        self._draw_waveform()
        self._safe_after(self._ANIM_MS, self._animate)

    def _draw_waveform(self) -> None:
        now = self._time_get()
        dt = 0.016
        if self._last_ts > 0:
            dt = min(now - self._last_ts, 0.05)
        self._last_ts = now

        k = 1.0 - math.pow(0.035, dt)
        self._live_amp += (self._tgt_amp - self._live_amp) * k
        self._live_spd += (self._tgt_spd - self._live_spd) * k
        self._live_r += (self._tgt_r - self._live_r) * k
        self._live_g += (self._tgt_g - self._live_g) * k
        self._live_b += (self._tgt_b - self._live_b) * k
        if self._flash > 0:
            self._flash = max(0.0, self._flash - dt * 1.6)
        self._time += dt * self._live_spd

        r = int(self._live_r)
        g = int(self._live_g)
        b = int(self._live_b)
        w = self._W
        cy = self._H // 2
        amp = self._live_amp
        t = self._time
        step = self._STEP

        # ── Background layers (dimmer, wider) ──
        for li in range(self._LAYERS - 1, 0, -1):
            frac = li / self._LAYERS
            bright = 0.08 + (1.0 - frac) * 0.22
            lw = max(0.8, 1.8 - li * 0.22)
            ph_off = li * 0.62
            fm = 1.0 + li * 0.18
            self._draw_layer(w, cy, amp, t, r, g, b, bright, lw, ph_off, fm, step)

        # ── Center bright line ──
        self._draw_layer(w, cy, amp * 0.82, t * 1.02, r, g, b, 0.78, 2.0, 0.0, 1.0, step)

        # ── Flash overlay ──
        if self._flash > 0.008:
            fc = _TCOLOR_to_hex(r, g, b)
            alpha = int(self._flash * 50)
            self.canvas.create_rectangle(
                0, 0, w, self._H,
                fill=fc, outline="", stipple="gray25",
            )

    def _draw_layer(self, w, cy, amp, t, r, g, b, bright, lw, ph, fm, step):
        pts = []
        for x in range(0, w + step, step):
            nx = x / w
            env = _edge_fade(nx)
            s1 = math.sin(nx * 6.8  * fm + t * 2.05 + ph)
            s2 = math.sin(nx * 10.2 * fm + t * 1.62 + ph * 1.35)
            val = (s1 * 0.7 + s2 * 0.3) * amp * env
            pts.append(x)
            pts.append(int(cy + val))
        if pts:
            color = _TCOLOR_to_hex(r, g, b)
            self.canvas.create_line(
                *pts, fill=color, width=lw, capstyle="round",
            )

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

    @staticmethod
    def _time_get() -> float:
        return time.perf_counter()


def _edge_fade(nx: float) -> float:
    """Smoothstep envelope: fade edges, flat center."""
    fade_zone = 0.18
    if nx <= 0 or nx >= 1:
        return 0
    if nx < fade_zone:
        t = nx / fade_zone
        return t * t * (3 - 2 * t)
    if nx > 1 - fade_zone:
        t = (1 - nx) / fade_zone
        return t * t * (3 - 2 * t)
    return 1.0


def _TCOLOR_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


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
        root.mainloop()
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
