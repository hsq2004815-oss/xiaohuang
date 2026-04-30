from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.audio_capture_service import AudioDependencyError, build_recording_path, record_wav
from xiaohuang.config_service import load_config
from xiaohuang.logging_service import configure_logging
from xiaohuang.stt_client_service import (
    SttServerError,
    SttServerUnavailable,
    check_server_health,
    request_transcription,
)
from xiaohuang.vad_recording_service import record_until_silence
from xiaohuang.wake_word_service import is_wake_phrase_detected, parse_wake_phrases


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
    wake_dir = recording_dir / "wake"
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

    try:
        while True:
            wake_path = build_recording_path(wake_dir)
            try:
                record_wav(
                    wake_path,
                    duration_seconds=args.wake_window_seconds,
                    sample_rate=sample_rate,
                    channels=channels,
                    device_id=device_id,
                )
                wake_response = request_transcription(wake_path, args.server_url)
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

            wake_text = str(wake_response.get("text", ""))
            if args.debug:
                print(f"Wake check transcription: {wake_text}")
            if not is_wake_phrase_detected(wake_text, wake_phrases):
                continue

            print("Wake word detected.")
            logger.info("Wake word detected from text: %s", wake_text)
            if args.countdown > 0:
                for remaining in range(args.countdown, 0, -1):
                    print(f"{remaining}...")
                    time.sleep(1)

            print("Listening for command...")
            command_path = build_recording_path(recording_dir)
            try:
                command_result = record_until_silence(
                    command_path,
                    device_id=device_id,
                    sample_rate=sample_rate,
                    channels=channels,
                    max_seconds=args.max_seconds,
                    silence_seconds=args.silence_seconds,
                )
                command_response = request_transcription(command_result.path, args.server_url)
            except AudioDependencyError as exc:
                logger.error(str(exc))
                print(str(exc))
                return 2
            except (SttServerUnavailable, SttServerError) as exc:
                logger.error(str(exc))
                print(f"{exc}\nSTT server is required for wake_loop.py.")
                return 6
            except Exception as exc:
                logger.exception("Command capture failed.")
                print(f"Command capture failed: {exc}")
                return 1

            command_text = str(command_response.get("text", ""))
            print(f"Command transcription: {command_text}")
            print(f"actual_recording_seconds={command_result.duration_seconds:.2f}")
            print(f"stop_reason={command_result.stop_reason}")
            logger.info("Command transcription: %s", command_text)

            if args.once:
                return 0
            print("Listening for wake phrase...")
    except KeyboardInterrupt:
        print("Wake loop stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
