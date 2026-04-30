from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from xiaohuang.audio_capture_service import (
    compute_audio_levels,
    _load_sounddevice,
    _load_soundfile,
)


DEFAULT_ENERGY_THRESHOLD = 600.0
DEFAULT_NOISE_CALIBRATION_SECONDS = 0.5
DEFAULT_BLOCK_SECONDS = 0.1

STOP_SILENCE_AFTER_SPEECH = "silence_after_speech"
STOP_MAX_SECONDS_REACHED = "max_seconds_reached"
STOP_NO_SPEECH_DETECTED = "no_speech_detected"


@dataclass(frozen=True)
class VadRecordingResult:
    path: Path
    duration_seconds: float
    peak_amplitude: int
    rms_amplitude: float
    speech_detected: bool
    stop_reason: str
    energy_threshold: float


@dataclass(frozen=True)
class VadState:
    elapsed_seconds: float = 0.0
    speech_seconds: float = 0.0
    silence_after_speech_seconds: float = 0.0
    speech_started: bool = False
    stop_reason: str | None = None


def block_peak_rms(audio_block: Any) -> tuple[int, float]:
    levels = compute_audio_levels(audio_block)
    return levels.peak_amplitude, levels.rms_amplitude


def is_speech_block(audio_block: Any, energy_threshold: float) -> bool:
    _peak, rms = block_peak_rms(audio_block)
    return rms >= energy_threshold


def calculate_noise_threshold(noise_rms_values: Iterable[float]) -> float:
    values = [float(value) for value in noise_rms_values if value >= 0]
    if not values:
        return DEFAULT_ENERGY_THRESHOLD

    average_noise = sum(values) / len(values)
    peak_noise = max(values)
    return max(DEFAULT_ENERGY_THRESHOLD, average_noise * 3.0, peak_noise * 1.8)


def update_vad_state(
    state: VadState,
    *,
    speech_detected_in_block: bool,
    block_seconds: float,
    min_speech_seconds: float,
    silence_seconds: float,
    max_seconds: float,
) -> VadState:
    if state.stop_reason is not None:
        return state

    elapsed_seconds = state.elapsed_seconds + block_seconds
    speech_seconds = state.speech_seconds
    silence_after_speech_seconds = state.silence_after_speech_seconds
    speech_started = state.speech_started
    stop_reason: str | None = None

    if speech_detected_in_block:
        speech_seconds += block_seconds
        silence_after_speech_seconds = 0.0
        if speech_seconds >= min_speech_seconds:
            speech_started = True
    elif speech_started:
        silence_after_speech_seconds += block_seconds

    epsilon = 1e-9
    if speech_started and silence_after_speech_seconds >= silence_seconds - epsilon:
        stop_reason = STOP_SILENCE_AFTER_SPEECH
    elif elapsed_seconds >= max_seconds - epsilon:
        stop_reason = STOP_MAX_SECONDS_REACHED if speech_started else STOP_NO_SPEECH_DETECTED

    return replace(
        state,
        elapsed_seconds=elapsed_seconds,
        speech_seconds=speech_seconds,
        silence_after_speech_seconds=silence_after_speech_seconds,
        speech_started=speech_started,
        stop_reason=stop_reason,
    )


def record_until_silence(
    output_path: str | Path,
    device_id: int | None = None,
    sample_rate: int = 16000,
    channels: int = 1,
    max_seconds: float = 10,
    min_speech_seconds: float = 0.3,
    silence_seconds: float = 0.8,
    energy_threshold: float | None = None,
    calibrate_noise: bool = False,
) -> VadRecordingResult:
    if max_seconds <= 0:
        raise ValueError("max_seconds must be greater than 0.")
    if min_speech_seconds <= 0:
        raise ValueError("min_speech_seconds must be greater than 0.")
    if silence_seconds <= 0:
        raise ValueError("silence_seconds must be greater than 0.")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be greater than 0.")
    if channels <= 0:
        raise ValueError("channels must be greater than 0.")

    sounddevice = _load_sounddevice()
    soundfile = _load_soundfile()
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    threshold = float(energy_threshold) if energy_threshold is not None else DEFAULT_ENERGY_THRESHOLD
    if energy_threshold is None and calibrate_noise:
        threshold = _calibrate_energy_threshold(
            sounddevice=sounddevice,
            sample_rate=sample_rate,
            channels=channels,
            device_id=device_id,
        )

    block_size = max(1, int(sample_rate * DEFAULT_BLOCK_SECONDS))
    block_seconds = block_size / sample_rate
    blocks: list[Any] = []
    state = VadState()

    with sounddevice.InputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
        device=device_id,
        blocksize=block_size,
    ) as stream:
        while state.stop_reason is None:
            block, _overflowed = stream.read(block_size)
            blocks.append(block.copy() if hasattr(block, "copy") else block)
            state = update_vad_state(
                state,
                speech_detected_in_block=is_speech_block(block, threshold),
                block_seconds=block_seconds,
                min_speech_seconds=min_speech_seconds,
                silence_seconds=silence_seconds,
                max_seconds=max_seconds,
            )

    audio = _concatenate_audio_blocks(blocks)
    soundfile.write(destination, audio, sample_rate, subtype="PCM_16")
    levels = compute_audio_levels(audio)
    duration_seconds = _audio_duration_seconds(audio, sample_rate)

    return VadRecordingResult(
        path=destination,
        duration_seconds=duration_seconds,
        peak_amplitude=levels.peak_amplitude,
        rms_amplitude=levels.rms_amplitude,
        speech_detected=state.speech_started,
        stop_reason=state.stop_reason or STOP_MAX_SECONDS_REACHED,
        energy_threshold=threshold,
    )


def _calibrate_energy_threshold(
    *,
    sounddevice: Any,
    sample_rate: int,
    channels: int,
    device_id: int | None,
) -> float:
    frames = max(1, int(sample_rate * DEFAULT_NOISE_CALIBRATION_SECONDS))
    noise = sounddevice.rec(
        frames,
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
        device=device_id,
    )
    sounddevice.wait()
    _peak, rms = block_peak_rms(noise)
    return calculate_noise_threshold([rms])


def _concatenate_audio_blocks(blocks: list[Any]) -> Any:
    try:
        import numpy
    except ImportError:
        return [sample for block in blocks for sample in _iter_block_samples(block)]

    if not blocks:
        return numpy.zeros((0,), dtype="int16")
    return numpy.concatenate(blocks, axis=0)


def _audio_duration_seconds(audio: Any, sample_rate: int) -> float:
    if hasattr(audio, "shape"):
        frames = int(audio.shape[0])
    else:
        frames = len(audio)
    return frames / sample_rate


def _iter_block_samples(block: Any) -> Iterable[int]:
    if hasattr(block, "flatten"):
        for value in block.flatten():
            yield int(value)
        return

    for value in block:
        if isinstance(value, (list, tuple)):
            for nested in _iter_block_samples(value):
                yield nested
        else:
            yield int(value)
