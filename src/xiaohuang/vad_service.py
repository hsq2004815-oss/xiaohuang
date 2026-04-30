from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FixedDurationVad:
    """V0.1 placeholder: records a fixed duration instead of running real VAD."""

    duration_seconds: int = 5

    def get_recording_duration_seconds(self) -> int:
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be greater than 0.")
        return self.duration_seconds

