from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


class AudioDependencyError(RuntimeError):
    pass


def build_recording_path(output_dir: str | Path, timestamp: str | None = None) -> Path:
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(output_dir) / f"test_{stamp}.wav"


def list_input_devices() -> list[dict[str, Any]]:
    sounddevice = _load_sounddevice()
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

    sounddevice = _load_sounddevice()
    soundfile = _load_soundfile()
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


def _load_sounddevice():
    try:
        import sounddevice
    except ImportError as exc:
        raise AudioDependencyError(
            "Missing dependency: sounddevice. Install project dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc
    return sounddevice


def _load_soundfile():
    try:
        import soundfile
    except ImportError as exc:
        raise AudioDependencyError(
            "Missing dependency: soundfile. Install project dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc
    return soundfile

