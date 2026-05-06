from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("stt_server")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.api_error_service import STT_ENGINE_ERROR, STT_SERVER_ERROR
from xiaohuang.api_schemas import build_error_response, build_ok_response
from xiaohuang.app_config_service import XiaoHuangConfig, load_config
from xiaohuang.request_context_service import generate_request_id
from xiaohuang.stt_server_service import (
    PathGuardError,
    resolve_recording_wav_path,
)
from xiaohuang.stt_service import SenseVoiceTranscriber, resolve_stt_device


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local-only XiaoHuang STT server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Keep this as 127.0.0.1 for local-only use.")
    parser.add_argument("--port", type=int, default=8766, help="Bind port.")
    return parser.parse_args()


SERVER_VERSION = "1.0.2"
SERVER_SERVICE = "xiaohuang-stt-server"

CAPABILITIES = {
    "transcribe": True,
    "health": True,
    "request_id": True,
    "error_envelope": True,
}


class SttServerState:
    def __init__(self, transcriber: SenseVoiceTranscriber, model_init_seconds: float, stt_device: str) -> None:
        self.transcriber = transcriber
        self.model_init_seconds = model_init_seconds
        self.stt_device = stt_device
        self.start_time = time.time()
        self.last_error: dict[str, Any] | None = None

    @property
    def uptime_seconds(self) -> float:
        return round(time.time() - self.start_time, 2)

    def record_error(self, code: str, message: str, request_id: str) -> None:
        self.last_error = {
            "code": code,
            "message": message,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def make_handler(state: SttServerState):
    class SttRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request_id = generate_request_id()
            if self.path != "/health":
                self._write_json(
                    404,
                    build_error_response(
                        request_id, type="health",
                        code="STT_SERVER_ERROR", message="Not found.", retryable=False,
                    ),
                )
                return
            health = build_ok_response(request_id, type="health")
            health.update(build_health_fields(state))
            self._write_json(200, health)

        def do_POST(self) -> None:
            request_id = generate_request_id()
            if self.path != "/transcribe":
                self._write_json(
                    404,
                    build_error_response(
                        request_id, type="command",
                        code="STT_SERVER_ERROR", message="Not found.", retryable=False,
                    ),
                )
                return

            request_start = time.perf_counter()
            try:
                payload = self._read_json()
                wav_path = payload.get("wav_path")
                if not wav_path:
                    state.record_error("STT_SERVER_ERROR", "Missing wav_path.", request_id)
                    self._write_json(
                        400,
                        build_error_response(
                            request_id, type="command",
                            code="STT_SERVER_ERROR", message="Missing wav_path.", retryable=False,
                        ),
                    )
                    return

                try:
                    safe_wav_path = resolve_recording_wav_path(wav_path, PROJECT_ROOT)
                except PathGuardError as exc:
                    state.record_error("STT_SERVER_ERROR", str(exc), request_id)
                    self._write_json(
                        400,
                        build_error_response(
                            request_id, type="command",
                            code="STT_SERVER_ERROR", message=str(exc), retryable=False,
                        ),
                    )
                    return

                transcribe_start = time.perf_counter()
                text = state.transcriber.transcribe(safe_wav_path)
                transcribe_seconds = time.perf_counter() - transcribe_start
                total_seconds = time.perf_counter() - request_start
                response = build_ok_response(request_id, type="command", text=text)
                response["server_model_init_seconds"] = round(state.model_init_seconds, 2)
                response["transcribe_seconds"] = round(transcribe_seconds, 2)
                response["total_seconds"] = round(total_seconds, 2)
                if not text:
                    response.setdefault("meta", {})
                    response["meta"]["no_speech"] = True
                    response["meta"]["empty_text"] = True
                self._write_json(200, response)
            except Exception:
                logger.exception("STT transcription failed request_id=%s", request_id)
                state.record_error(STT_ENGINE_ERROR, "Transcription failed.", request_id)
                self._write_json(
                    500,
                    build_error_response(
                        request_id, type="command",
                        code=STT_ENGINE_ERROR, message="Transcription failed.", retryable=True,
                    ),
                )

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


def build_health_fields(state: SttServerState) -> dict[str, Any]:
    return {
        "status": "ready",
        "server_model_init_seconds": round(state.model_init_seconds, 2),
        "service": SERVER_SERVICE,
        "version": SERVER_VERSION,
        "uptime_seconds": state.uptime_seconds,
        "model_loaded": _is_model_loaded(state.transcriber),
        "stt_device": state.stt_device,
        "capabilities": dict(CAPABILITIES),
        "last_error": state.last_error,
    }


def build_transcriber_from_config(
    config: XiaoHuangConfig,
    *,
    transcriber_cls: Any = SenseVoiceTranscriber,
    torch_module: Any | None = "auto",
    warn: Callable[[str], None] | None = None,
) -> SenseVoiceTranscriber:
    stt_device = resolve_stt_device(config.stt.device, torch_module=torch_module, warn=warn)
    return transcriber_cls(
        model_name=config.stt.model_name,
        language=config.stt.language,
        use_itn=config.stt.use_itn,
        device=stt_device,
    )


def _is_model_loaded(transcriber: Any) -> bool:
    return transcriber._model is not None if hasattr(transcriber, "_model") else True


def _startup_warning(message: str) -> None:
    logger.warning(message)
    print(f"WARNING: {message}", flush=True)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    if args.host != "127.0.0.1":
        print("Refusing to bind non-local host. Use 127.0.0.1 for local XiaoHuang prototypes.", flush=True)
        return 2

    config = load_config()
    transcriber = build_transcriber_from_config(config, warn=_startup_warning)
    print(f"stt_device={transcriber.device}", flush=True)
    print("Loading SenseVoiceSmall model...", flush=True)
    model_init_seconds = transcriber.ensure_model_loaded()
    state = SttServerState(
        transcriber=transcriber,
        model_init_seconds=model_init_seconds,
        stt_device=transcriber.device,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    print(f"STT server ready on http://{args.host}:{args.port}", flush=True)
    print(f"server_model_init_seconds={model_init_seconds:.2f} (server startup only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("STT server stopped.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
