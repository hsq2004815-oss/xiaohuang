from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from xiaohuang.audio_playback_service import play_audio_file
from xiaohuang.llm_reply_service import generate_llm_reply_result
from xiaohuang.reply_service import generate_reply
from xiaohuang.tts_service import (
    MissingTtsDependencyError,
    synthesize_tts_to_mp3,
)


@dataclass(frozen=True)
class ReplyPipelineConfig:
    enable_llm: bool
    enable_tts: bool
    llm_config: Any = None
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_output_dir: Path = Path("data/tts")


@dataclass(frozen=True)
class ReplyPipelineResult:
    reply_text: str
    reply_source: str
    source_note: str | None
    tts_path: Path | None = None
    tts_played: bool = False
    tts_error: str | None = None


def generate_reply_pipeline_result(
    command_text: str,
    config: ReplyPipelineConfig,
    *,
    rule_reply_func: Callable[..., str] = generate_reply,
    llm_reply_func: Callable[..., Any] = generate_llm_reply_result,
    tts_func: Callable[..., Path] = synthesize_tts_to_mp3,
    play_audio_func: Callable[..., bool] = play_audio_file,
    on_debug: Callable[[str], None] | None = None,
    on_before_tts: Callable[[str], None] | None = None,
    playback_warn: Callable[[str], None] | None = None,
) -> ReplyPipelineResult:
    if config.enable_llm and config.llm_config is not None and config.llm_config.is_configured:
        reply_result = llm_reply_func(
            command_text, config=config.llm_config, on_debug=on_debug,
        )
        reply_text = reply_result.text
        reply_source = reply_result.source
    elif config.enable_llm:
        reply_text = rule_reply_func(command_text)
        reply_source = "rule_fallback_no_key"
    else:
        reply_text = rule_reply_func(command_text)
        reply_source = "rule"

    source_note = _source_note_for_source(reply_source)

    tts_path: Path | None = None
    tts_played = False
    tts_error: str | None = None

    if config.enable_tts:
        _safe_call(on_before_tts, reply_text)
        try:
            tts_path = tts_func(reply_text, config.tts_output_dir, voice=config.tts_voice)
            tts_played = _call_play_audio(play_audio_func, tts_path, playback_warn)
            if not tts_played:
                tts_error = "Audio playback returned False"
        except MissingTtsDependencyError as exc:
            tts_error = str(exc)
        except Exception as exc:
            tts_error = f"TTS failed: {exc}"

    return ReplyPipelineResult(
        reply_text=reply_text,
        reply_source=reply_source,
        source_note=source_note,
        tts_path=tts_path,
        tts_played=tts_played,
        tts_error=tts_error,
    )


def _safe_call(callback: Callable[..., None] | None, *args: Any) -> None:
    if callback is None:
        return
    try:
        callback(*args)
    except Exception:
        pass


def _call_play_audio(
    play_func: Callable[..., bool],
    path: Path,
    warn_callback: Callable[[str], None] | None,
) -> bool:
    try:
        return play_func(path, warn=warn_callback)
    except TypeError:
        return play_func(path)


def _source_note_for_source(source: str) -> str | None:
    if source in ("rule", "llm"):
        return None
    if source == "rule_fallback_no_key":
        return "DeepSeek 未配置 key，已使用本地回复"
    if source == "rule_fallback_error":
        return "DeepSeek 不可用，已使用本地回复"
    if source == "rule_fallback_empty":
        return "DeepSeek 返回为空，已使用本地回复"
    if source == "rule_fallback_length":
        return "DeepSeek 输出被截断，已使用本地回复"
    if source == "tool_unavailable":
        return "当前版本还不能执行工具"
    return None
