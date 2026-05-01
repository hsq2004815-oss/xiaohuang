from __future__ import annotations

import argparse
import math
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.audio_playback_service import play_audio_file
from xiaohuang.config_service import load_config
from xiaohuang.logging_service import configure_logging
from xiaohuang.llm_reply_service import generate_llm_reply_result, load_deepseek_config
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
from xiaohuang.reply_service import generate_reply
from xiaohuang.stt_client_service import SttServerError, SttServerUnavailable, check_server_health, request_transcription
from xiaohuang.tts_service import DEFAULT_TTS_VOICE, MissingTtsDependencyError, synthesize_tts_to_mp3
from xiaohuang.wake_loop_service import WakeLoopOptions, run_wake_loop_once
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
    return parser.parse_args()


class VoiceOverlayApp:
    def __init__(self, root, *, stop_event: threading.Event, debug: bool = False) -> None:
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
    app = VoiceOverlayApp(root, stop_event=stop_event, debug=args.debug)

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
) -> None:
    _stt_call_count = {"n": 0}

    def _overlay_stt(path, server_url):
        _stt_call_count["n"] += 1
        try:
            return request_transcription(path, server_url)
        except (SttServerUnavailable, SttServerError) as exc:
            if _stt_call_count["n"] == 1:
                # wake check — skip this window
                if debug:
                    print(f"Wake check STT failed, skipped this window: {exc}")
                logger.warning("Wake check STT failed, skipped this window: %s", exc)
                return {"text": ""}
            raise

    while not stop_event.is_set():
        _stt_call_count["n"] = 0
        try:
            result = run_wake_loop_once(
                options,
                on_state_change=lambda state, payload=None: _handle_wake_state(app, state, payload),
                on_wake_text=(lambda text: print(f"Wake check transcription: {text}")) if debug else None,
                on_wake_match=(lambda match: _print_wake_match(match)) if debug else None,
                on_command_text=(lambda text: print(f"Command transcription: {text}")) if debug else None,
                request_transcription_func=_overlay_stt,
            )
            if stop_event.is_set():
                break
            logger.info("Overlay command transcription: %s", result.command_text)
            app.thread_safe_set_state(STATE_REPLYING)
            if enable_llm:
                if not llm_config.is_configured:
                    reply_text = generate_reply(result.command_text)
                    reply_source = "rule_fallback_no_key"
                else:
                    reply_result = generate_llm_reply_result(
                        result.command_text,
                        config=llm_config,
                        on_debug=_make_llm_debug_handler(logger, debug),
                    )
                    reply_text = reply_result.text
                    reply_source = reply_result.source
            else:
                reply_text = generate_reply(result.command_text)
                reply_source = "rule"
            if debug:
                print(f"XiaoHuang reply: {reply_text}")
                print(f"Reply source: {reply_source}")
            logger.info("Overlay reply: %s (source=%s)", reply_text, reply_source)
            source_note = _source_note_for_overlay(reply_source)
            app.thread_safe_set_state(
                STATE_RESULT,
                build_reply_result_text(result.command_text, reply_text, source_note),
            )

            if enable_tts and not stop_event.is_set():
                app.thread_safe_set_state(STATE_SPEAKING, reply_text)
                try:
                    tts_path = synthesize_tts_to_mp3(reply_text, tts_output_dir, voice=tts_voice)
                    logger.info("Generated TTS reply: %s", tts_path)
                    play_audio_file(tts_path, warn=lambda message: _playback_warning(logger, message))
                except MissingTtsDependencyError as exc:
                    _warn(logger, str(exc))
                    app.thread_safe_set_state(STATE_ERROR, str(exc))
                except Exception as exc:
                    _warn(logger, f"TTS failed: {exc}")
                    app.thread_safe_set_state(STATE_ERROR, f"TTS failed: {exc}")

            if debug:
                print(f"Post-response cooldown: {post_response_cooldown:.1f}s")
            if stop_event.wait(post_response_cooldown):
                break
            app.thread_safe_set_state(STATE_IDLE)
            stop_event.wait(0.5)
        except (SttServerUnavailable, SttServerError) as exc:
            if stop_event.is_set():
                break
            logger.warning("Command STT failed: %s", exc)
            if debug:
                print(f"Command STT failed: {exc}")
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


def _handle_wake_state(app: VoiceOverlayApp, state: str, payload: str | None = None) -> None:
    if state == STATE_RESULT:
        return
    app.thread_safe_set_state(state, payload)


def _warn(logger, message: str) -> None:
    print(f"Warning: {message}")
    logger.warning(message)


def _playback_warning(logger, message: str) -> None:
    print(message)
    logger.warning(message)


def _print_wake_match(match: WakeMatchResult) -> None:
    detected = "true" if match.detected else "false"
    print(f"Wake match: detected={detected} score={match.score:.2f} reason={match.reason}")


def _make_llm_debug_handler(logger, debug_enabled: bool):
    if not debug_enabled:
        return None
    def _log(msg: str) -> None:
        print(f"DeepSeek debug: {msg}")
        logger.info("DeepSeek debug: %s", msg)
    return _log


def _source_note_for_overlay(source: str) -> str | None:
    if source in ("rule", "llm"):
        return None
    if source == "rule_fallback_no_key":
        return "DeepSeek 未配置 key，已使用本地回复"
    if source == "rule_fallback_error":
        return "DeepSeek 不可用，已使用本地回复"
    if source == "rule_fallback_empty":
        return "DeepSeek 返回为空，已使用本地回复"
    if source == "rule_fallback_length":
        return "DeepSeek 输出被截断，已使用本地回复"
    if source == "tool_unavailable":
        return "当前版本还不能执行工具"
    return None


if __name__ == "__main__":
    raise SystemExit(main())
