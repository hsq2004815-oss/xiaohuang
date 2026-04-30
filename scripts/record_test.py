from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.audio_capture_service import (
    AudioDependencyError,
    build_recording_path,
    list_input_devices,
    record_wav,
)
from xiaohuang.config_service import load_config
from xiaohuang.logging_service import configure_logging
from xiaohuang.vad_service import FixedDurationVad


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record a fixed-duration WAV sample.")
    parser.add_argument("--device", type=int, default=None, help="Input device ID from check_audio_devices.py.")
    parser.add_argument("--seconds", type=int, default=None, help="Recording duration. Defaults to config value.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    logger = configure_logging(
        PROJECT_ROOT / config["logging"]["directory"],
        "record_test",
        config["logging"]["level"],
    )

    try:
        devices = list_input_devices()
    except AudioDependencyError as exc:
        logger.error(str(exc))
        print(str(exc))
        return 2
    except Exception as exc:
        logger.exception("Failed to query input devices.")
        print(f"Failed to query input devices: {exc}")
        return 1

    if devices:
        print("Available input devices:")
        for device in devices:
            print(
                f"[{device['id']}] {device['name']} | "
                f"max_input_channels={device['max_input_channels']} | "
                f"default_samplerate={device['default_samplerate']} Hz"
            )

    device_id = args.device
    if device_id is None:
        config_device = config["audio"].get("device_id")
        device_id = int(config_device) if config_device is not None else None

    duration = args.seconds or int(config["recording"]["duration_seconds"])
    vad = FixedDurationVad(duration_seconds=duration)
    output_dir = PROJECT_ROOT / config["recording"]["output_dir"]
    output_path = build_recording_path(output_dir)

    print(f"Recording {vad.get_recording_duration_seconds()} second(s)...")
    try:
        saved_path = record_wav(
            output_path,
            duration_seconds=vad.get_recording_duration_seconds(),
            sample_rate=int(config["audio"]["sample_rate"]),
            channels=int(config["audio"]["channels"]),
            device_id=device_id,
        )
    except AudioDependencyError as exc:
        logger.error(str(exc))
        print(str(exc))
        return 2
    except Exception as exc:
        logger.exception("Recording failed.")
        print(f"Recording failed: {exc}")
        return 1

    logger.info("Saved recording to %s", saved_path)
    print(f"Saved recording: {saved_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

