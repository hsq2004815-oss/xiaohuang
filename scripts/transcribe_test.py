from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.config_service import load_config
from xiaohuang.logging_service import configure_logging
from xiaohuang.stt_service import MissingDependencyError, SenseVoiceTranscriber, TranscriptionError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe a WAV file with FunASR SenseVoiceSmall.")
    parser.add_argument("wav_path", type=Path, help="Path to a WAV file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    logger = configure_logging(
        PROJECT_ROOT / config["logging"]["directory"],
        "transcribe_test",
        config["logging"]["level"],
    )

    transcriber = SenseVoiceTranscriber(
        model_name=config["stt"]["model_name"],
        language=config["stt"]["language"],
        use_itn=bool(config["stt"]["use_itn"]),
    )

    try:
        text = transcriber.transcribe(args.wav_path)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        print(str(exc))
        return 2
    except MissingDependencyError as exc:
        logger.error(str(exc))
        print(str(exc))
        return 3
    except TranscriptionError as exc:
        logger.error(str(exc))
        print(str(exc))
        return 1
    except Exception as exc:
        logger.exception("Unexpected transcription failure.")
        print(f"Unexpected transcription failure: {exc}")
        return 1

    logger.info("Transcription finished for %s", args.wav_path)
    print("Transcription:")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

