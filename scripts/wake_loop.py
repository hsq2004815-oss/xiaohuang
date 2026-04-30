from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.audio_capture_service import AudioDependencyError
from xiaohuang.config_service import load_config
from xiaohuang.logging_service import configure_logging
from xiaohuang.stt_client_service import (
    SttServerError,
    SttServerUnavailable,
    check_server_health,
)
from xiaohuang.wake_loop_service import WakeLoopOptions, run_wake_loop_once
from xiaohuang.wake_word_service import parse_wake_phrases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Console wake-word prototype using short-window STT matching.")
    parser.add_argument("--device", type=int, default=None, help="Input device ID. Defaults to config audio.device_id or 0.")
    parser.add_argument("--wake-window-seconds", type=float, default=2.0, help="Short recording window for wake checks. Defaults to 2.")
    parser.add_argument("--wake-phrases", default="小黄,小黄小黄", help="Comma-separated wake phrases.")
    parser.add_argument("--server-url", default="http://127.0.0.1:8766", help="Local STT server URL.")
    parser.add_argument("--max-seconds", type=float, default=10.0, help="Maximum VAD command recording duration. Defaults to 10.")
    parser.add_argument("--silence-seconds", type=float, default=0.8, help="Silence duration after command speech before VAD stops.")
    parser.add_argument("--countdown", type=int, default=0, help="Countdown seconds before command recording after wake detection.")
    parser.add_argument("--once", action="store_true", help="Exit after one wake detection and command transcription.")
    parser.add_argument("--debug", action="store_true", help="Print wake-window transcription text. Normal mode only prints state transitions.")
    parser.add_argument("--keep-wake-recordings", action="store_true", help="Keep short wake-check WAV files under data/recordings/wake for debugging.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    logger = configure_logging(
        PROJECT_ROOT / config["logging"]["directory"],
        "wake_loop",
        config["logging"]["level"],
    )
    audio_config = config.get("audio", {})
    recording_config = config.get("recording", {})
    device_id = args.device
    if device_id is None:
        config_device = audio_config.get("device_id")
        device_id = int(config_device) if config_device is not None else 0
    sample_rate = int(audio_config.get("sample_rate", 16000))
    channels = int(audio_config.get("channels", 1))
    recording_dir = PROJECT_ROOT / recording_config.get("output_dir", "data/recordings")
    wake_phrases = parse_wake_phrases(args.wake_phrases)

    try:
        health = check_server_health(args.server_url)
    except (SttServerUnavailable, SttServerError) as exc:
        logger.error(str(exc))
        print(f"{exc}\nStart STT server before running wake_loop.py.")
        return 6

    print(f"STT server ready: {args.server_url} ({health.get('status', 'ok')})")
    print(f"Waiting for wake phrase(s): {', '.join(wake_phrases)}")
    print("Listening for wake phrase...")
    logger.info("Wake loop started with device=%s server=%s", device_id, args.server_url)
    options = WakeLoopOptions(
        device_id=device_id,
        server_url=args.server_url,
        wake_window_seconds=args.wake_window_seconds,
        wake_phrases=wake_phrases,
        max_seconds=args.max_seconds,
        silence_seconds=args.silence_seconds,
        sample_rate=sample_rate,
        channels=channels,
        recording_dir=recording_dir,
        keep_wake_recordings=args.keep_wake_recordings,
    )

    try:
        while True:
            try:
                result = run_wake_loop_once(
                    options,
                    on_state_change=lambda state, payload=None: _print_state(state, payload),
                    on_wake_text=(lambda text: print(f"Wake check transcription: {text}")) if args.debug else None,
                    delete_wake_recording_func=lambda path: _delete_wake_recording(path, logger),
                    before_command_func=lambda: _run_countdown(args.countdown),
                )
            except AudioDependencyError as exc:
                logger.error(str(exc))
                print(str(exc))
                return 2
            except (SttServerUnavailable, SttServerError) as exc:
                logger.error(str(exc))
                print(f"{exc}\nSTT server is required for wake_loop.py.")
                return 6
            except Exception as exc:
                logger.exception("Wake check failed.")
                print(f"Wake check failed: {exc}")
                return 1

            print(f"actual_recording_seconds={result.actual_recording_seconds:.2f}")
            print(f"stop_reason={result.stop_reason}")
            logger.info("Wake word detected from text: %s", result.wake_text)
            logger.info("Command transcription: %s", result.command_text)

            if args.once:
                return 0
            print("Listening for wake phrase...")
    except KeyboardInterrupt:
        print("Wake loop stopped.")
        return 0


def _delete_wake_recording(path: Path, logger) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        message = f"Warning: failed to delete wake recording {path}: {exc}"
        print(message)
        logger.warning(message)


def _run_countdown(countdown: int) -> None:
    if countdown <= 0:
        return
    for remaining in range(countdown, 0, -1):
        print(f"{remaining}...")
        time.sleep(1)


def _print_state(state: str, payload: str | None = None) -> None:
    if state == "wake_checking":
        return
    if state == "wake_detected":
        print("Wake word detected.")
        return
    if state == "listening":
        print("Listening for command...")
        return
    if state == "transcribing":
        return
    if state == "result":
        print(f"Command transcription: {payload or ''}")
        return


if __name__ == "__main__":
    raise SystemExit(main())
