from __future__ import annotations

from typing import Any, Callable

from xiaohuang.reply_pipeline_service import (
    ReplyPipelineConfig,
    ReplyPipelineResult,
    generate_reply_pipeline_result,
)


def generate_reply_runtime_result(
    command_text: str,
    *,
    config: ReplyPipelineConfig,
    on_debug: Callable[[str], None] | None = None,
    playback_warn: Callable[[str], None] | None = None,
    latency_tracker=None,
    on_before_tts: Callable[[str], None] | None = None,
    on_after_tts: Callable[[], None] | None = None,
    pipeline_func: Callable[..., ReplyPipelineResult] = generate_reply_pipeline_result,
    conversation_context: str | None = None,
) -> ReplyPipelineResult:
    tts_started = False

    def _before_tts(text: str) -> None:
        nonlocal tts_started
        tts_started = True
        if on_before_tts is not None:
            on_before_tts(text)

    kwargs = {}
    if conversation_context is not None:
        kwargs["conversation_context"] = conversation_context
    try:
        return pipeline_func(
            command_text,
            config=config,
            on_debug=on_debug,
            on_before_tts=_before_tts,
            playback_warn=playback_warn,
            latency_tracker=latency_tracker,
            **kwargs,
        )
    finally:
        if tts_started and on_after_tts is not None:
            on_after_tts()
