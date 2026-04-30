from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xiaohuang.audio_capture_service import AudioLevels


@dataclass(frozen=True)
class ListenOnceOptions:
    device_id: int | None
    seconds: int
    countdown: int
    channels: int
    samplerate: int


@dataclass(frozen=True)
class TimingStats:
    record_seconds: float
    model_init_seconds: float | None
    transcribe_seconds: float
    total_seconds: float
    server_model_init_seconds: float | None = None


def resolve_listen_once_options(args: Any, config: dict[str, Any]) -> ListenOnceOptions:
    audio = config.get("audio", {})
    recording = config.get("recording", {})
    config_device = audio.get("device_id")

    return ListenOnceOptions(
        device_id=_coalesce(args.device, config_device, None),
        seconds=int(_coalesce(args.seconds, recording.get("duration_seconds"), 5)),
        countdown=int(_coalesce(args.countdown, None, 3)),
        channels=int(_coalesce(args.channels, audio.get("channels"), 1)),
        samplerate=int(_coalesce(args.samplerate, audio.get("sample_rate"), 16000)),
    )


def build_audio_summary(path: Path, levels: AudioLevels) -> str:
    lines = [
        f"Saved recording: {path}",
        f"Peak amplitude: {levels.peak_amplitude}",
        f"RMS amplitude: {levels.rms_amplitude:.2f}",
    ]
    if levels.is_too_quiet:
        lines.append("Warning: audio level is very low; this may be silence or the wrong input device.")
    if levels.is_clipping:
        lines.append("Warning: audio is clipping; input volume may be too high.")
    return "\n".join(lines)


def build_timing_summary(stats: TimingStats) -> str:
    lines = [
        "Timing diagnostics:",
        f"record_seconds={stats.record_seconds:.2f}",
    ]
    if stats.model_init_seconds is not None:
        lines.append(f"model_init_seconds={stats.model_init_seconds:.2f}")
    if stats.server_model_init_seconds is not None:
        lines.append(f"server_model_init_seconds={stats.server_model_init_seconds:.2f} (server startup only)")
    lines.extend(
        [
            f"transcribe_seconds={stats.transcribe_seconds:.2f}",
            f"total_seconds={stats.total_seconds:.2f}",
        ]
    )
    return "\n".join(lines)


def should_allow_local_fallback(args: Any) -> bool:
    return bool(getattr(args, "use_server", False) and getattr(args, "allow_local_fallback", False))


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None
