from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
from typing import Any, Iterable


class AudioDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioLevels:
    peak_amplitude: int
    rms_amplitude: float
    is_too_quiet: bool
    is_clipping: bool


def build_recording_path(output_dir: str | Path, timestamp: str | None = None) -> Path:
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(output_dir) / f"test_{stamp}.wav"


def classify_input_device(name: str) -> str:
    normalized = name.lower()
    not_recommended_terms = ("speaker", "output", "立体声混音")
    recommended_terms = ("microphone", "mic", "input", "麦克风")

    if any(term in normalized for term in not_recommended_terms):
        return "not recommended"
    if any(term in normalized for term in recommended_terms):
        return "recommended"
    return "unknown"


def list_input_devices() -> list[dict[str, Any]]:
    sounddevice = load_sounddevice()
    devices = sounddevice.query_devices()
    input_devices: list[dict[str, Any]] = []

    for index, device in enumerate(devices):
        max_input_channels = int(device.get("max_input_channels", 0))
        if max_input_channels <= 0:
            continue
        input_devices.append(
            {
                "id": index,
                "name": device.get("name", ""),
                "max_input_channels": max_input_channels,
                "default_samplerate": int(device.get("default_samplerate", 0)),
                "recommendation": classify_input_device(str(device.get("name", ""))),
            }
        )

    return input_devices


def record_wav(
    output_path: str | Path,
    duration_seconds: int,
    sample_rate: int = 16000,
    channels: int = 1,
    device_id: int | None = None,
) -> Path:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than 0.")

    sounddevice = load_sounddevice()
    soundfile = load_soundfile()
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    frames = int(duration_seconds * sample_rate)
    audio = sounddevice.rec(
        frames,
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
        device=device_id,
    )
    sounddevice.wait()
    soundfile.write(destination, audio, sample_rate, subtype="PCM_16")
    return destination


def analyze_wav(path: str | Path) -> AudioLevels:
    soundfile = load_soundfile()
    audio, _sample_rate = soundfile.read(Path(path), dtype="int16", always_2d=False)
    return compute_audio_levels(audio)


def compute_audio_levels(audio: Any) -> AudioLevels:
    values = [abs(int(sample)) for sample in _iter_samples(audio)]
    if not values:
        return AudioLevels(peak_amplitude=0, rms_amplitude=0.0, is_too_quiet=True, is_clipping=False)

    peak = max(values)
    rms = math.sqrt(sum(value * value for value in values) / len(values))
    return AudioLevels(
        peak_amplitude=peak,
        rms_amplitude=rms,
        is_too_quiet=rms < 300,
        is_clipping=peak >= 32000,
    )


def _iter_samples(audio: Any) -> Iterable[int]:
    if hasattr(audio, "flatten"):
        for value in audio.flatten():
            yield int(value)
        return

    for value in audio:
        if isinstance(value, (list, tuple)):
            for nested in _iter_samples(value):
                yield nested
        else:
            yield int(value)


def load_sounddevice():
    try:
        import sounddevice
    except ImportError as exc:
        raise AudioDependencyError(
            "Missing dependency: sounddevice. Install project dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc
    return sounddevice


def load_soundfile():
    try:
        import soundfile
    except ImportError as exc:
        raise AudioDependencyError(
            "Missing dependency: soundfile. Install project dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc
    return soundfile


def _load_sounddevice():
    return load_sounddevice()


def _load_soundfile():
    return load_soundfile()
