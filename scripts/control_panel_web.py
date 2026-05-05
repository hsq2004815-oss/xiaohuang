"""XiaoHuang Web Control Panel — pywebview launcher.

Optional dependency: pywebview (pip install pywebview)
Falls back to Tkinter control_panel.py if pywebview is not available.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
FRONTEND_DIR = PROJECT_ROOT / "frontend" / "control_panel"

sys.path.insert(0, str(SRC_DIR))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XiaoHuang Web Control Panel")
    parser.add_argument(
        "--config", default=None,
        help="Path to config.json. Defaults to %%USERPROFILE%%\\.xiaohuang\\config.json",
    )
    parser.add_argument("--debug", action="store_true", help="Enable pywebview debug mode")
    parser.add_argument("--width", type=int, default=1120, help="Window width (default 1120)")
    parser.add_argument("--height", type=int, default=760, help="Window height (default 760)")
    parser.add_argument("--devtools", action="store_true", help="Enable Chrome DevTools in webview")
    return parser.parse_args()


def _check_frontend() -> Path:
    index_html = FRONTEND_DIR / "index.html"
    if not index_html.exists():
        print(f"Frontend file not found: {index_html}")
        print("Expected structure: frontend/control_panel/index.html")
        sys.exit(2)
    return index_html


def _try_import_webview():
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False


def main() -> int:
    args = _parse_args()

    if not _try_import_webview():
        print("pywebview is not installed.")
        print("Install it with: pip install pywebview")
        print("")
        print("Alternatively, use the Tkinter control panel:")
        print(f'  python scripts\\control_panel.py --config "{args.config}"')
        return 3

    import webview

    index_path = _check_frontend()

    from xiaohuang.control_panel_web_service import ControlPanelWebApi
    api = ControlPanelWebApi(config_path=args.config)

    url = index_path.as_uri()
    window = webview.create_window(
        title="小黄控制中心",
        url=url,
        width=args.width,
        height=args.height,
        js_api=api,
        resizable=True,
    )

    webview.start(debug=args.debug or args.devtools)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
