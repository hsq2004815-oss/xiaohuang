from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from xiaohuang.audio_capture_service import build_recording_path, record_wav
from xiaohuang.overlay_state_service import (
    STATE_LISTENING,
    STATE_RESULT,
    STATE_TRANSCRIBING,
    STATE_WAKE_CHECKING,
    STATE_WAKE_DETECTED,
)
from xiaohuang.stt_client_service import request_transcription
from xiaohuang.vad_recording_service import record_until_silence
from xiaohuang.wake_word_service import WakeMatchResult, detect_wake_phrase, parse_wake_phrases

STT_MODE_WAKE_CHECK = "wake_check"
STT_MODE_COMMAND = "command"


@dataclass(frozen=True)
class WakeLoopOptions:
    device_id: int
    server_url: str
    wake_window_seconds: float
    wake_phrases: str | Iterable[str]
    max_seconds: float
    silence_seconds: float
    sample_rate: int
    channels: int
    recording_dir: Path
    keep_wake_recordings: bool = False
    wake_aliases: str | Iterable[str] | None = None


@dataclass(frozen=True)
class WakeLoopResult:
    wake_text: str
    command_text: str
    command_path: Path
    actual_recording_seconds: float
    stop_reason: str


StateCallback = Callable[[str, str | None], None]
TextCallback = Callable[[str], None]
WakeMatchCallback = Callable[[WakeMatchResult], None]


def run_wake_loop_once(
    options: WakeLoopOptions,
    *,
    on_state_change: StateCallback | None = None,
    on_wake_text: TextCallback | None = None,
    on_wake_match: WakeMatchCallback | None = None,
    on_command_text: TextCallback | None = None,
    record_wav_func: Callable[..., Path] = record_wav,
    record_until_silence_func: Callable[..., Any] = record_until_silence,
    request_transcription_func: Callable[..., dict[str, Any]] = request_transcription,
    build_recording_path_func: Callable[..., Path] = build_recording_path,
    delete_wake_recording_func: Callable[[Path], None] | None = None,
    before_command_func: Callable[[], None] | None = None,
) -> WakeLoopResult:
    wake_dir = options.recording_dir / "wake"
    wake_phrases = parse_wake_phrases(options.wake_phrases)

    while True:
        _emit(on_state_change, STATE_WAKE_CHECKING)
        wake_path = build_recording_path_func(wake_dir)
        record_wav_func(
            wake_path,
            duration_seconds=options.wake_window_seconds,
            sample_rate=options.sample_rate,
            channels=options.channels,
            device_id=options.device_id,
        )
        try:
            wake_response = _call_transcription(
                request_transcription_func, wake_path, options.server_url, STT_MODE_WAKE_CHECK,
            )
        finally:
            if not options.keep_wake_recordings:
                _delete_wake_recording(wake_path, delete_wake_recording_func)

        wake_text = str(wake_response.get("text", ""))
        if on_wake_text is not None:
            on_wake_text(wake_text)
        wake_match = detect_wake_phrase(wake_text, wake_phrases, alias_phrases=options.wake_aliases)
        if on_wake_match is not None:
            on_wake_match(wake_match)
        if not wake_match.detected:
            continue

        _emit(on_state_change, STATE_WAKE_DETECTED)
        if before_command_func is not None:
            before_command_func()
        _emit(on_state_change, STATE_LISTENING)
        command_path = build_recording_path_func(options.recording_dir)
        command_result = record_until_silence_func(
            command_path,
            device_id=options.device_id,
            sample_rate=options.sample_rate,
            channels=options.channels,
            max_seconds=options.max_seconds,
            silence_seconds=options.silence_seconds,
        )
        _emit(on_state_change, STATE_TRANSCRIBING)
        command_response = _call_transcription(
                request_transcription_func, command_result.path, options.server_url, STT_MODE_COMMAND,
            )
        command_text = str(command_response.get("text", ""))
        if on_command_text is not None:
            on_command_text(command_text)
        _emit(on_state_change, STATE_RESULT, command_text)
        return WakeLoopResult(
            wake_text=wake_text,
            command_text=command_text,
            command_path=Path(command_result.path),
            actual_recording_seconds=float(command_result.duration_seconds),
            stop_reason=str(command_result.stop_reason),
        )


def _call_transcription(
    func: Callable[..., Any],
    wav_path: Path,
    server_url: str,
    mode: str,
) -> dict[str, Any]:
    try:
        return func(wav_path, server_url, mode=mode)
    except TypeError:
        return func(wav_path, server_url)


def _emit(callback: StateCallback | None, state: str, payload: str | None = None) -> None:
    if callback is not None:
        callback(state, payload)


def _delete_wake_recording(path: Path, delete_wake_recording_func: Callable[[Path], None] | None) -> None:
    if delete_wake_recording_func is not None:
        delete_wake_recording_func(path)
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"Warning: failed to delete wake recording {path}: {exc}")
