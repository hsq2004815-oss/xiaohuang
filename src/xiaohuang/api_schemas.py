from __future__ import annotations

from typing import Any

from xiaohuang.api_error_service import STT_SERVER_ERROR, build_error
from xiaohuang.request_context_service import generate_request_id


def build_ok_response(
    request_id: str | None = None,
    *,
    type: str | None = None,
    text: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "request_id": request_id or generate_request_id(),
        "type": type or "unknown",
        "text": text,
        "error": None,
        "meta": meta or {},
    }


def build_error_response(
    request_id: str | None = None,
    *,
    type: str | None = None,
    code: str = STT_SERVER_ERROR,
    message: str = "",
    retryable: bool = True,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "request_id": request_id or generate_request_id(),
        "type": type or "unknown",
        "text": "",
        "error": build_error(code=code, message=message, retryable=retryable),
        "meta": meta or {},
    }
