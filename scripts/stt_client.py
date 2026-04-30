from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.stt_client_service import SttServerError, SttServerUnavailable, request_transcription


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a WAV file to the local XiaoHuang STT server.")
    parser.add_argument("wav_path", type=Path, help="Path to a WAV file.")
    parser.add_argument("--server-url", default="http://127.0.0.1:8766", help="Local STT server URL.")
    parser.add_argument("--timeout", type=float, default=120.0, help="Request timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        response = request_transcription(args.wav_path, args.server_url, timeout_seconds=args.timeout)
    except SttServerUnavailable as exc:
        print(str(exc))
        return 2
    except SttServerError as exc:
        print(str(exc))
        return 1

    print("Transcription:")
    print(response["text"])
    print("Timing diagnostics:")
    print(f"server_model_init_seconds={response['server_model_init_seconds']:.2f} (server startup only)")
    print(f"transcribe_seconds={response['transcribe_seconds']:.2f}")
    print(f"total_seconds={response['total_seconds']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
