"""XiaoHuang standalone text chat window launcher."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
FRONTEND_DIR = PROJECT_ROOT / "frontend" / "text_chat"

sys.path.insert(0, str(SRC_DIR))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XiaoHuang Text Chat Window")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.json. Defaults to %%USERPROFILE%%\\.xiaohuang\\config.json",
    )
    parser.add_argument("--debug", action="store_true", help="Enable pywebview debug mode")
    parser.add_argument("--width", type=int, default=1280, help="Window width (default 1280)")
    parser.add_argument("--height", type=int, default=780, help="Window height (default 780)")
    parser.add_argument("--devtools", action="store_true", help="Enable Chrome DevTools in webview")
    return parser.parse_args()


def _check_frontend() -> Path:
    index_html = FRONTEND_DIR / "index.html"
    if not index_html.exists():
        print(f"Frontend file not found: {index_html}")
        print("Expected structure: frontend/text_chat/index.html")
        sys.exit(2)
    return index_html


def main() -> int:
    args = _parse_args()

    try:
        import webview
    except ImportError:
        print("pywebview is not installed.")
        print("Install it with: pip install pywebview")
        return 3

    from xiaohuang.text_chat_web_service import TextChatWebApi

    index_path = _check_frontend()
    api = TextChatWebApi(config_path=args.config)

    webview.create_window(
        title="小黄文本对话",
        url=index_path.as_uri(),
        width=args.width,
        height=args.height,
        js_api=api,
        resizable=True,
    )
    webview.start(debug=args.debug or args.devtools)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
