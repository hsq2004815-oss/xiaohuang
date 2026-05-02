from __future__ import annotations

import argparse
import math
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

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
from xiaohuang.llm_reply_service import load_deepseek_config
from xiaohuang.overlay_state_service import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_REPLYING,
    STATE_RESULT,
    STATE_SPEAKING,
    STATE_TRANSCRIBING,
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
from xiaohuang.audio_capture_service import build_recording_path
from xiaohuang.stt_client_service import SttServerError, SttServerUnavailable, check_server_health, request_transcription
from xiaohuang.tts_service import DEFAULT_TTS_VOICE
from xiaohuang.vad_recording_service import record_until_silence
from xiaohuang.wake_loop_service import STT_MODE_COMMAND, STT_MODE_WAKE_CHECK, WakeLoopOptions, run_wake_loop_once
from xiaohuang.wake_word_service import DEFAULT_WAKE_ALIASES, WakeMatchResult, parse_wake_phrases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the XiaoHuang Tkinter voice overlay prototype.")
    parser.add_argument("--device", type=int, default=None, help="Input device ID. Defaults to config audio.device_id or 0.")
    parser.add_argument("--server-url", default="http://127.0.0.1:8766", help="Local STT server URL.")
    parser.add_argument("--wake-window-seconds", type=float, default=3.0, help="Short recording window for wake checks. Defaults to 3.")
    parser.add_argument("--wake-phrases", default="小黄,小黄小黄", help="Comma-separated wake phrases.")
    parser.add_argument("--wake-aliases", default=",".join(DEFAULT_WAKE_ALIASES), help="Comma-separated low-confidence wake aliases.")
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
    return parser.parse_args()


class VoiceOverlayApp:
    def __init__(self, root, *, stop_event: threading.Event, debug: bool = False, start_hidden: bool = False) -> None:
        self.root = root
        self.stop_event = stop_event
        self.debug = debug
        self.state = STATE_IDLE
        self.phase = 0.0
        self.closed = False
        self._after_ids: set[str] = set()
        self._build_ui()
        self.set_state(STATE_IDLE)
        self._animate()
        if start_hidden:
            try:
                self.root.withdraw()
            except Exception:
                pass

    def _build_ui(self) -> None:
        self.root.title("小黄")
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
        status = get_overlay_status_text(state, detail)
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
    app = VoiceOverlayApp(root, stop_event=stop_event, debug=args.debug, start_hidden=args.resident_hidden)

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

    if args.debug:
        print(f"STT server ready: {args.server_url} ({health.get('status', 'ok')})")

    audio_config = config.get("audio", {})
    recording_config = config.get("recording", {})
    device_id = args.device
    if device_id is None:
        config_device = audio_config.get("device_id")
        device_id = int(config_device) if config_device is not None else 0
    recording_dir = PROJECT_ROOT / recording_config.get("output_dir", "data/recordings")
    options = WakeLoopOptions(
        device_id=device_id,
        server_url=args.server_url,
        wake_window_seconds=args.wake_window_seconds,
        wake_phrases=parse_wake_phrases(args.wake_phrases),
        wake_aliases=parse_wake_phrases(args.wake_aliases),
        max_seconds=args.max_seconds,
        silence_seconds=args.silence_seconds,
        sample_rate=int(audio_config.get("sample_rate", 16000)),
        channels=int(audio_config.get("channels", 1)),
        recording_dir=recording_dir,
        keep_wake_recordings=False,
    )

    tts_output_dir = PROJECT_ROOT / args.tts_output_dir
    post_response_cooldown = resolve_post_response_cooldown(args.enable_tts, args.post_response_cooldown)
    llm_config = load_deepseek_config(
        timeout_seconds=args.llm_timeout,
        model_override=args.llm_model,
        base_url_override=args.llm_base_url,
        max_tokens_override=args.llm_max_tokens,
    )
    if args.enable_llm:
        if not llm_config.is_configured:
            if args.debug:
                print("DeepSeek API key 未配置，已使用本地规则回复")
            logger.info("--enable-llm specified but DEEPSEEK_API_KEY is not set; using local rule replies")
        elif args.debug:
            print(f"LLM enabled: model={llm_config.model} max_tokens={llm_config.max_tokens} timeout={llm_config.timeout_seconds}s")
    if args.debug:
        print(f"TTS enabled: {args.enable_tts}")
    session_config = ConversationSessionConfig(
        enabled=args.conversation_session,
        timeout_seconds=args.session_timeout,
        max_turns=args.max_session_turns,
        followup_timeout_seconds=args.followup_timeout,
        max_session_seconds=args.max_session_seconds,
        max_no_speech_retries=args.max_no_speech_retries,
    )
    if args.debug and session_config.enabled:
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
            args.debug,
            stop_event,
            args.enable_tts,
            args.tts_voice,
            tts_output_dir,
            post_response_cooldown,
            args.enable_llm,
            llm_config,
            args.resident_hidden,
            session_config,
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

    while not stop_event.is_set():
        try:
            turn_tracker = LatencyTracker()
            turn_tracker.start("turn_total_ms")

            on_wake_shown: Callable[[], None] | None = None
            if resident_hidden:
                on_wake_shown = lambda: (
                    app.show_overlay(),
                    app.thread_safe_set_state(STATE_WAKE_DETECTED),
                )

            result = run_wake_loop_once(
                options,
                on_state_change=lambda state, payload=None: _handle_wake_state(app, state, payload),
                on_wake_text=(lambda text: _safe_print(f"Wake check transcription: {text}")) if debug else None,
                on_wake_match=(lambda match: _print_wake_match(match)) if debug else None,
                on_command_text=(lambda text: _safe_print(f"Command transcription: {text}")) if debug else None,
                on_wake_detected=on_wake_shown,
                request_transcription_func=_overlay_stt,
                latency_tracker=turn_tracker,
            )
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
            )
            pipeline_result = generate_reply_pipeline_result(
                result.command_text,
                config=pipeline_config,
                on_debug=_make_llm_debug_handler(logger, debug),
                on_before_tts=lambda text: app.thread_safe_set_state(STATE_SPEAKING, text),
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
                    build_reply_result_text(result.command_text, pipeline_result.reply_text, pipeline_result.source_note),
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
                        pipeline_result = generate_reply_pipeline_result(
                            next_text, config=pipeline_config,
                            on_debug=_make_llm_debug_handler(logger, debug),
                            on_before_tts=lambda t: app.thread_safe_set_state(STATE_SPEAKING, t),
                            playback_warn=lambda m: _playback_warning(logger, m),
                            latency_tracker=st,
                        )
                    _safe_print(f"XiaoHuang: {pipeline_result.reply_text}")
                    logger.info("Overlay reply: %s (source=%s)", pipeline_result.reply_text, pipeline_result.reply_source)
                    st.end("turn_total_ms")
                    logger.info(format_latency_summary(st.summary_ms(), turn=turn_count + 1, source=pipeline_result.reply_source))
                    app.thread_safe_set_state(
                        STATE_RESULT,
                        build_reply_result_text(next_text, pipeline_result.reply_text, pipeline_result.source_note),
                    )
                    exit_phrase_detected = True
                    if stop_event.wait(post_response_cooldown):
                        break
                    break

                pipeline_result = generate_reply_pipeline_result(
                    next_text, config=pipeline_config,
                    on_debug=_make_llm_debug_handler(logger, debug),
                    on_before_tts=lambda t: app.thread_safe_set_state(STATE_SPEAKING, t),
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
                    "Session ended: reason=%s turn_count=%s max_turns=%s elapsed_seconds=%.1f "
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
