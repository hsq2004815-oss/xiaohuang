from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SttServerUnavailable(RuntimeError):
    pass


class SttServerError(RuntimeError):
    pass


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
        if 500 <= exc.code < 600:
            raise SttServerUnavailable(f"STT server error at {server_url}: HTTP {exc.code}") from exc
        raise SttServerUnavailable(f"STT server unavailable at {server_url}: HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SttServerUnavailable(f"STT server unavailable at {server_url}: {exc}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SttServerError(f"STT server returned invalid JSON: {body}") from exc

    if not data.get("ok"):
        raise SttServerError(_extract_error_message(data))
    return data


def _extract_error_message(data: dict[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, dict):
        code = error.get("code", "UNKNOWN")
        message = error.get("message", "")
        return f"{code}: {message}"
    if isinstance(error, str) and error:
        return error
    return "STT server returned ok=false."


def request_transcription(wav_path: str | Path, server_url: str, timeout_seconds: float = 120.0) -> dict[str, Any]:
    payload = json.dumps(build_transcribe_payload(wav_path)).encode("utf-8")
    endpoint = server_url.rstrip("/") + "/transcribe"
    request = Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        if 500 <= exc.code < 600:
            raise SttServerUnavailable(f"STT server error at {server_url}: HTTP {exc.code}") from exc
        raise SttServerUnavailable(f"STT server unavailable at {server_url}: HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SttServerUnavailable(f"STT server unavailable at {server_url}: {exc}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SttServerError(f"STT server returned invalid JSON: {body}") from exc

    if not data.get("ok"):
        raise SttServerError(_extract_error_message(data))
    return data
