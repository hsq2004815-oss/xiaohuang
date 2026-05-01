from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_TTS_VOICE = "zh-CN-XiaoxiaoNeural"


class MissingTtsDependencyError(RuntimeError):
    pass


def clean_tts_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    return cleaned or "我在。"


def build_tts_output_path(output_dir: Path, timestamp: str | None = None) -> Path:
    resolved_timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(output_dir) / f"tts_{resolved_timestamp}.mp3"


def synthesize_tts_to_mp3(
    text: str,
    output_dir: Path,
    *,
    voice: str = DEFAULT_TTS_VOICE,
    rate: str = "+0%",
    volume: str = "+0%",
    pitch: str = "+0Hz",
    edge_tts_module: Any | None = None,
) -> Path:
    edge_tts = edge_tts_module if edge_tts_module is not None else _load_edge_tts()
    output_path = build_tts_output_path(Path(output_dir))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_save_edge_tts(edge_tts, clean_tts_text(text), output_path, voice, rate, volume, pitch))
    return output_path


def _load_edge_tts() -> Any:
    try:
        import edge_tts
    except ImportError as exc:
        raise MissingTtsDependencyError(
            "edge-tts is not installed. Install it with: python -m pip install edge-tts"
        ) from exc
    return edge_tts


async def _save_edge_tts(edge_tts: Any, text: str, output_path: Path, voice: str, rate: str, volume: str, pitch: str) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
    await communicate.save(str(output_path))
