from __future__ import annotations


def resolve_post_response_cooldown(enable_tts: bool, requested_seconds: float | None) -> float:
    if requested_seconds is not None:
        return max(0.0, float(requested_seconds))
    return 6.0 if enable_tts else 3.5
