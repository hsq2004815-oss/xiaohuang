from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.audio_capture_service import AudioDependencyError, list_input_devices
from xiaohuang.config_service import load_config
from xiaohuang.logging_service import configure_logging


def main() -> int:
    config = load_config()
    logger = configure_logging(
        PROJECT_ROOT / config["logging"]["directory"],
        "check_audio_devices",
        config["logging"]["level"],
    )

    try:
        devices = list_input_devices()
    except AudioDependencyError as exc:
        logger.error(str(exc))
        print(str(exc))
        return 2
    except Exception as exc:
        logger.exception("Failed to enumerate audio devices.")
        print(f"Failed to enumerate audio devices: {exc}")
        return 1

    if not devices:
        logger.warning("No input audio devices found.")
        print("No input audio devices found.")
        return 0

    print("Available input devices:")
    for device in devices:
        print(
            f"[{device['id']}] {device['name']} | "
            f"max_input_channels={device['max_input_channels']} | "
            f"default_samplerate={device['default_samplerate']} Hz"
        )
    logger.info("Listed %s input audio device(s).", len(devices))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

