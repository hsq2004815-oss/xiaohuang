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

TOOL_DENIED_REPLY = "该操作不在安全白名单中，当前版本还不能执行。"


@dataclass(frozen=True)
class ReplyPipelineConfig:
    enable_llm: bool
    enable_tts: bool
    llm_config: Any = None
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_output_dir: Path = Path("data/tts")
    persona: str | None = None


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
    latency_tracker: Any | None = None,
    project_root: Any = None,
    conversation_context: str | None = None,
) -> ReplyPipelineResult:
    _track = _make_track(latency_tracker)

    # Try capability router first (V1.4-A)
    capability_handled = _try_capability_route(
        command_text,
        config,
        tts_func,
        play_audio_func,
        playback_warn,
        on_before_tts,
        latency_tracker,
        project_root,
    )
    if capability_handled is not None:
        return capability_handled

    if config.enable_llm and config.llm_config is not None and config.llm_config.is_configured:
        _track("llm_ms", start=True)
        reply_result = llm_reply_func(
            command_text,
            config=config.llm_config,
            on_debug=on_debug,
            persona=config.persona,
            conversation_context=conversation_context,
        )
        _track("llm_ms", start=False)
        reply_text = reply_result.text
        reply_source = reply_result.source
    elif config.enable_llm:
        reply_text = rule_reply_func(command_text)
        reply_source = "rule_fallback_no_key"
    else:
        reply_text = rule_reply_func(command_text)
        reply_source = "rule"

    source_note = _source_note_for_source(reply_source)
    tts_path, tts_played, tts_error = _run_tts(
        reply_text, config, tts_func, play_audio_func, playback_warn, on_before_tts, latency_tracker=latency_tracker,
    )

    return ReplyPipelineResult(
        reply_text=reply_text,
        reply_source=reply_source,
        source_note=source_note,
        tts_path=tts_path,
        tts_played=tts_played,
        tts_error=tts_error,
    )


def _try_capability_route(
    command_text: str,
    config: ReplyPipelineConfig,
    tts_func: Callable[..., Path],
    play_audio_func: Callable[..., bool],
    playback_warn: Callable[[str], None] | None,
    on_before_tts: Callable[[str], None] | None,
    latency_tracker: Any | None,
    project_root: Any,
) -> ReplyPipelineResult | None:
    try:
        from xiaohuang.capabilities.local_commands.service import (
            execute_capability,
            route_capability,
        )
    except Exception:
        return None

    decision = route_capability(command_text)
    if not decision.is_task_request:
        return None

    if decision.can_execute and decision.command:
        result = execute_capability(decision, project_root=project_root)
        reply_text = result.message
        reply_source = "capability"
        source_note = _source_note_for_source(reply_source)
        tts_path, tts_played, tts_error = _run_tts(
            reply_text, config, tts_func, play_audio_func, playback_warn, on_before_tts,
            latency_tracker=latency_tracker,
        )
        return ReplyPipelineResult(
            reply_text=reply_text,
            reply_source=reply_source,
            source_note=source_note,
            tts_path=tts_path,
            tts_played=tts_played,
            tts_error=tts_error,
        )

    if decision.reason in ("not_allowed", "capability_disabled"):
        reply_text = decision.message or TOOL_DENIED_REPLY
        reply_source = "tool_denied"
        source_note = _source_note_for_source(reply_source)
        tts_path, tts_played, tts_error = _run_tts(
            reply_text, config, tts_func, play_audio_func, playback_warn, on_before_tts,
        )
        return ReplyPipelineResult(
            reply_text=reply_text,
            reply_source=reply_source,
            source_note=source_note,
            tts_path=tts_path,
            tts_played=tts_played,
            tts_error=tts_error,
        )

    # Should not reach here — route_capability covers all cases.
    return None


def _run_tts(
    reply_text: str,
    config: ReplyPipelineConfig,
    tts_func: Callable[..., Path],
    play_audio_func: Callable[..., bool],
    playback_warn: Callable[[str], None] | None,
    on_before_tts: Callable[[str], None] | None,
    latency_tracker: Any | None = None,
) -> tuple[Path | None, bool, str | None]:
    _track = _make_track(latency_tracker)
    if not config.enable_tts:
        return None, False, None
    _safe_call(on_before_tts, reply_text)
    try:
        _track("tts_synthesis_ms", start=True)
        tts_path = tts_func(reply_text, config.tts_output_dir, voice=config.tts_voice)
        _track("tts_synthesis_ms", start=False)
        _track("tts_playback_ms", start=True)
        tts_played = _call_play_audio(play_audio_func, tts_path, playback_warn)
        _track("tts_playback_ms", start=False)
        if not tts_played:
            return tts_path, False, "Audio playback returned False"
        return tts_path, True, None
    except MissingTtsDependencyError as exc:
        return None, False, str(exc)
    except Exception as exc:
        return None, False, f"TTS failed: {exc}"


def _make_track(tracker: Any | None):
    if tracker is None:
        return lambda name, **kw: None
    def _t(name, *, start=False):
        if start:
            tracker.start(name)
        else:
            tracker.end(name)
    return _t


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
    if source == "capability":
        return None
    if source == "rule_fallback_no_key":
        return "LLM 未配置 key，已使用本地回复"
    if source == "rule_fallback_error":
        return "LLM 不可用，已使用本地回复"
    if source == "rule_fallback_empty":
        return "LLM 返回为空，已使用本地回复"
    if source == "rule_fallback_length":
        return "LLM 输出被截断，已使用本地回复"
    if source == "tool_unavailable":
        return "当前版本还不能执行工具"
    if source == "tool_denied":
        return "该操作不在安全白名单中"
    return None
