from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.wake_word_service import DEFAULT_WAKE_ALIASES, detect_wake_phrase, parse_wake_phrases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test XiaoHuang wake phrase text matching without recording audio.")
    parser.add_argument("text", help="Wake-check transcription text to test.")
    parser.add_argument("--wake-phrases", default="小黄,小黄小黄", help="Comma-separated wake phrases.")
    parser.add_argument("--wake-aliases", default=",".join(DEFAULT_WAKE_ALIASES), help="Comma-separated wake aliases.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = detect_wake_phrase(
        args.text,
        parse_wake_phrases(args.wake_phrases),
        alias_phrases=parse_wake_phrases(args.wake_aliases),
    )
    print(f"detected={str(result.detected).lower()}")
    print(f"score={result.score:.2f}")
    print(f"reason={result.reason}")
    print(f"normalized_text={result.normalized_text}")
    print(f"matched_phrase={result.matched_phrase or ''}")
    return 0 if result.detected else 1


if __name__ == "__main__":
    raise SystemExit(main())
