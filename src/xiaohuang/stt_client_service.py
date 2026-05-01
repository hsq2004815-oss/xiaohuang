from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SttServerUnavailable(RuntimeError):
    """Cannot reach STT server (DNS, refused, timeout, OSError)."""


class SttServerError(RuntimeError):
    """Base class for reachable STT server/API errors."""


class SttRequestError(SttServerError):
    """HTTP 4xx or client-side request issue accepted by server boundary."""


class SttServerInternalError(SttServerError):
    """HTTP 5xx returned by STT server."""


class SttApiError(SttServerError):
    """HTTP succeeded but response body has ok=false."""


class SttInvalidResponse(SttServerError):
    """Response body is not valid JSON or has unusable schema."""


def build_transcribe_payload(wav_path: str | Path) -> dict[str, str]:
    return {"wav_path": str(wav_path)}


def build_health_url(server_url: str) -> str:
    return server_url.rstrip("/") + "/health"


def check_server_health(server_url: str, timeout_seconds: float = 5.0) -> dict[str, Any]:
    request = Request(build_health_url(server_url), method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        _raise_for_http_error(exc, server_url)
    except (URLError, TimeoutError, OSError) as exc:
        raise SttServerUnavailable(f"STT server unavailable at {server_url}: {exc}") from exc
    return _parse_response_body(body)


def request_transcription(wav_path: str | Path, server_url: str, timeout_seconds: float = 120.0) -> dict[str, Any]:
    payload = json.dumps(build_transcribe_payload(wav_path)).encode("utf-8")
    endpoint = server_url.rstrip("/") + "/transcribe"
    request = Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        _raise_for_http_error(exc, server_url)
    except (URLError, TimeoutError, OSError) as exc:
        raise SttServerUnavailable(f"STT server unavailable at {server_url}: {exc}") from exc
    return _parse_response_body(body)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_http_error_body(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8")
    except Exception:
        return ""


def _raise_for_http_error(exc: HTTPError, server_url: str) -> None:
    body_text = _read_http_error_body(exc)
    if 400 <= exc.code < 500:
        _raise_with_body(exc, SttRequestError, server_url, body_text)
    elif 500 <= exc.code < 600:
        _raise_with_body(exc, SttServerInternalError, server_url, body_text)
    else:
        _raise_with_body(exc, SttServerError, server_url, body_text)


def _raise_with_body(
    exc: HTTPError,
    error_cls: type[SttServerError],
    server_url: str,
    body_text: str,
) -> None:
    detail = _format_error_from_body(body_text)
    if detail:
        raise error_cls(f"STT server error at {server_url}: HTTP {exc.code} — {detail}") from exc
    raise error_cls(f"STT server error at {server_url}: HTTP {exc.code}") from exc


def _format_error_from_body(body_text: str) -> str:
    if not body_text:
        return ""
    try:
        data = json.loads(body_text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if isinstance(error, dict):
        code = error.get("code", "")
        message = error.get("message", "")
        return f"{code}: {message}"
    if isinstance(error, str) and error:
        return error
    return ""


def _parse_response_body(body: str) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SttInvalidResponse("STT server returned invalid JSON") from exc

    if not isinstance(data, dict):
        raise SttInvalidResponse(f"STT server returned non-dict response: {type(data).__name__}")

    if data.get("ok") is True:
        return data

    if data.get("ok") is False:
        raise SttApiError(_extract_error_message(data))

    # ok field missing — fallback to backward-compat heuristics
    if "text" in data or "status" in data:
        return data

    raise SttInvalidResponse("STT server response missing ok field and has no text/status")


def _extract_error_message(data: dict[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, dict):
        code = error.get("code", "UNKNOWN")
        message = error.get("message", "")
        return f"{code}: {message}"
    if isinstance(error, str) and error:
        return error
    return "STT server returned ok=false."
