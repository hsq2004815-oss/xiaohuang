from __future__ import annotations

from typing import Any


STT_EMPTY_AUDIO = "STT_EMPTY_AUDIO"
STT_ENGINE_ERROR = "STT_ENGINE_ERROR"
STT_SERVER_ERROR = "STT_SERVER_ERROR"
STT_BAD_RESPONSE = "STT_BAD_RESPONSE"
STT_TIMEOUT = "STT_TIMEOUT"
STT_UNAVAILABLE = "STT_UNAVAILABLE"


def build_error(
    code: str,
    message: str,
    *,
    retryable: bool = True,
    detail: str | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if detail is not None:
        error["detail"] = detail
    return error
