from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from xiaohuang.audio_capture_service import build_recording_path
from xiaohuang.stt_client_service import SttServerError, SttServerUnavailable, request_transcription
from xiaohuang.vad_recording_service import record_until_silence


@dataclass(frozen=True)
class CommandRecordResult:
    command_text: str
    command_path: Path
    actual_recording_seconds: float
    stop_reason: str


def call_overlay_transcription(func: Callable[..., dict], wav_path: Path, server_url: str, mode: str) -> dict:
    try:
        return func(wav_path, server_url, mode=mode)
    except TypeError:
        return func(wav_path, server_url)


def record_and_transcribe(
    *,
    device_id: int,
    sample_rate: int,
    channels: int,
    max_seconds: float,
    silence_seconds: float,
    recording_dir: Path,
    server_url: str,
    transcribe_func: Callable[..., dict] = request_transcription,
    record_func=record_until_silence,
    build_recording_path_func=build_recording_path,
    stt_mode: str = "command",
    on_track_start: Callable[[str], None] | None = None,
    on_track_end: Callable[[str], None] | None = None,
) -> CommandRecordResult:
    _track_start = on_track_start or (lambda _name: None)
    _track_end = on_track_end or (lambda _name: None)

    command_path = build_recording_path_func(recording_dir)
    _track_start("command_record_ms")
    command_result = record_func(
        command_path,
        device_id=device_id,
        sample_rate=sample_rate,
        channels=channels,
        max_seconds=max_seconds,
        silence_seconds=silence_seconds,
    )
    _track_end("command_record_ms")
    _track_start("command_stt_ms")
    command_response = call_overlay_transcription(
        transcribe_func,
        command_result.path,
        server_url,
        stt_mode,
    )
    _track_end("command_stt_ms")

    return CommandRecordResult(
        command_text=str(command_response.get("text", "")),
        command_path=Path(command_result.path),
        actual_recording_seconds=float(command_result.duration_seconds),
        stop_reason=str(command_result.stop_reason),
    )


def record_command_transcribe(
    *,
    options,
    max_seconds: float,
    debug: bool = False,
    logger=None,
    record_func=record_until_silence,
    transcribe_func=request_transcription,
    on_track_start: Callable[[str], None] | None = None,
    on_track_end: Callable[[str], None] | None = None,
) -> str:
    try:
        result = record_and_transcribe(
            device_id=options.device_id,
            sample_rate=options.sample_rate,
            channels=options.channels,
            max_seconds=max_seconds,
            silence_seconds=options.silence_seconds,
            recording_dir=options.recording_dir,
            server_url=options.server_url,
            transcribe_func=transcribe_func,
            record_func=record_func,
            stt_mode="command",
            on_track_start=on_track_start,
            on_track_end=on_track_end,
        )
        return result.command_text
    except (SttServerUnavailable, SttServerError) as exc:
        if debug:
            _safe_print(f"Session command STT failed: {exc}")
        if logger is not None:
            logger.warning("Session command STT failed: %s", exc)
        return ""
    except Exception as exc:
        if logger is not None:
            logger.warning("Session command recording failed: %s", exc)
        return ""


def _safe_print(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        import sys
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))
