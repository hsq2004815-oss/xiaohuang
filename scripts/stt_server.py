from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.config_service import load_config
from xiaohuang.stt_server_service import build_error_response, build_success_response
from xiaohuang.stt_service import SenseVoiceTranscriber


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local-only XiaoHuang STT server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Keep this as 127.0.0.1 for local-only use.")
    parser.add_argument("--port", type=int, default=8766, help="Bind port.")
    return parser.parse_args()


class SttServerState:
    def __init__(self, transcriber: SenseVoiceTranscriber, model_init_seconds: float) -> None:
        self.transcriber = transcriber
        self.model_init_seconds = model_init_seconds


def make_handler(state: SttServerState):
    class SttRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/health":
                self._write_json(404, build_error_response("Not found."))
                return
            self._write_json(
                200,
                {
                    "ok": True,
                    "status": "ready",
                    "server_model_init_seconds": round(state.model_init_seconds, 2),
                },
            )

        def do_POST(self) -> None:
            if self.path != "/transcribe":
                self._write_json(404, build_error_response("Not found."))
                return

            request_start = time.perf_counter()
            try:
                payload = self._read_json()
                wav_path = payload.get("wav_path")
                if not wav_path:
                    self._write_json(400, build_error_response("Missing wav_path."))
                    return

                transcribe_start = time.perf_counter()
                text = state.transcriber.transcribe(Path(wav_path))
                transcribe_seconds = time.perf_counter() - transcribe_start
                total_seconds = time.perf_counter() - request_start
                self._write_json(
                    200,
                    build_success_response(
                        text=text,
                        server_model_init_seconds=state.model_init_seconds,
                        transcribe_seconds=transcribe_seconds,
                        total_seconds=total_seconds,
                    ),
                )
            except Exception as exc:
                self._write_json(500, build_error_response(str(exc)))

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body or "{}")

        def _write_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return SttRequestHandler


def main() -> int:
    args = parse_args()
    if args.host != "127.0.0.1":
        print("Refusing to bind non-local host. Use 127.0.0.1 for local XiaoHuang prototypes.")
        return 2

    config = load_config()
    transcriber = SenseVoiceTranscriber(
        model_name=config["stt"]["model_name"],
        language="auto",
        use_itn=True,
    )
    print("Loading SenseVoiceSmall model...")
    model_init_seconds = transcriber.ensure_model_loaded()
    state = SttServerState(transcriber=transcriber, model_init_seconds=model_init_seconds)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    print(f"STT server ready on http://{args.host}:{args.port}")
    print(f"server_model_init_seconds={model_init_seconds:.2f} (server startup only)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("STT server stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
