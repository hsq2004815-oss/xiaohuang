from __future__ import annotations

from typing import Any


def build_success_response(
    text: str,
    server_model_init_seconds: float,
    transcribe_seconds: float,
    total_seconds: float,
) -> dict[str, Any]:
    return {
        "ok": True,
        "text": text,
        "server_model_init_seconds": round(server_model_init_seconds, 2),
        "transcribe_seconds": round(transcribe_seconds, 2),
        "total_seconds": round(total_seconds, 2),
    }


def build_error_response(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": message,
    }
