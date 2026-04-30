from __future__ import annotations

from pathlib import Path
from typing import Any


class PathGuardError(ValueError):
    pass


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


def resolve_recording_wav_path(wav_path: str | Path, project_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    recordings_dir = (root / "data" / "recordings").resolve()
    candidate = Path(wav_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()

    if resolved.suffix.lower() != ".wav":
        raise PathGuardError("Only .wav files under data/recordings are allowed.")
    if not _is_relative_to(resolved, recordings_dir):
        raise PathGuardError("wav_path must stay under data/recordings.")
    if not resolved.exists():
        raise PathGuardError("wav_path does not exist.")
    if not resolved.is_file():
        raise PathGuardError("wav_path must point to a file.")
    return resolved


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
