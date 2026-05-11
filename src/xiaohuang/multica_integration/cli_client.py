"""Safe readonly Multica CLI client."""

from __future__ import annotations

import re
import subprocess
from typing import Callable, Sequence

from xiaohuang.multica_integration.models import MulticaCommandResult
from xiaohuang.multica_integration.safety import get_command_argv
from xiaohuang.multica_integration.safety import is_allowed_command

DEFAULT_TIMEOUT_SECONDS = 8.0
MAX_STREAM_CHARS = 4000

Runner = Callable[..., subprocess.CompletedProcess[str]]

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|apikey|token|password|secret)\b\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\b(authorization)\b\s*[:=]\s*(bearer\s+)?([^\s,;]+)"),
    re.compile(r"(?i)\bbearer\s+([^\s,;]+)"),
)


def run_multica_command(
    command_key: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    runner: Runner | None = None,
) -> MulticaCommandResult:
    key = str(command_key or "")
    if not is_allowed_command(key):
        return MulticaCommandResult(
            ok=False,
            command_key=key,
            returncode=-1,
            error_code="rejected_command",
            message="Multica command is not allowed.",
        )

    argv = list(get_command_argv(key))
    run = runner or subprocess.run
    try:
        completed = run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError:
        return MulticaCommandResult(
            ok=False,
            command_key=key,
            returncode=-1,
            error_code="multica_not_found",
            message="未找到 multica CLI。",
        )
    except subprocess.TimeoutExpired as exc:
        return MulticaCommandResult(
            ok=False,
            command_key=key,
            returncode=-1,
            stdout=_sanitize_stream(exc.stdout),
            stderr=_sanitize_stream(exc.stderr),
            error_code="multica_timeout",
            message="Multica command timed out.",
        )
    except OSError as exc:
        return MulticaCommandResult(
            ok=False,
            command_key=key,
            returncode=-1,
            error_code="multica_command_failed",
            message=str(exc),
        )

    stdout = _sanitize_stream(completed.stdout)
    stderr = _sanitize_stream(completed.stderr)
    ok = int(completed.returncode) == 0
    return MulticaCommandResult(
        ok=ok,
        command_key=key,
        returncode=int(completed.returncode),
        stdout=stdout,
        stderr=stderr,
        error_code="" if ok else "multica_nonzero_exit",
        message="ok" if ok else _compact_message(stderr or stdout or "Multica command failed."),
    )


def _sanitize_stream(value: object, *, limit: int = MAX_STREAM_CHARS) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value or "")
    text = _redact_sensitive_text(text)
    if len(text) > limit:
        return text[:limit].rstrip() + "...<truncated>"
    return text


def _redact_sensitive_text(text: str) -> str:
    value = str(text or "")
    value = _SENSITIVE_PATTERNS[0].sub(r"\g<1>=<redacted>", value)
    value = _SENSITIVE_PATTERNS[1].sub(r"\g<1>=<redacted>", value)
    value = _SENSITIVE_PATTERNS[2].sub("Bearer <redacted>", value)
    return value


def _compact_message(text: str) -> str:
    return " ".join(str(text or "").split())[:240]

