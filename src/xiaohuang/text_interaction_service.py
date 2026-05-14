from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from xiaohuang.app_config_service import load_config
from xiaohuang.llm_reply_service import load_llm_provider_config
from xiaohuang.reply_pipeline_service import ReplyPipelineConfig, ReplyPipelineResult
from xiaohuang.reply_runtime_service import generate_reply_runtime_result
from xiaohuang.text_task_confirmation_service import (
    build_pending_text_task,
    format_pending_task_reply,
)
from xiaohuang.text_task_intent_service import detect_text_task_intent
from xiaohuang.text_interaction_models import TextInteractionResult
from xiaohuang.text_interaction_session_service import TextInteractionSessionStore

_MAX_INPUT_CHARS = 1000
_PANEL_COMMAND_TERMS = (
    "启动小黄",
    "停止小黄",
    "重启小黄",
    "刷新状态",
    "打开日志目录",
    "导出诊断",
    "保存唤醒配置",
)
_PANEL_COMMAND_REPLY = (
    "这类运行控制建议使用控制面板上的对应按钮完成。"
    "我可以帮你解释当前状态或给出排查建议。"
)


def is_panel_control_command(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    return any(term.lower() in normalized for term in _PANEL_COMMAND_TERMS)


def run_text_interaction_turn(
    text: str,
    *,
    session_store: TextInteractionSessionStore,
    session_id: str = "default",
    config_path: Path | str | None = None,
    conversation_id: str | None = None,
    history_store: Any | None = None,
) -> TextInteractionResult:
    started = time.perf_counter()
    sid = str(session_id or "default").strip() or "default"
    user_text = str(text or "").strip()

    if not user_text:
        return _result(False, sid, started, error="文本不能为空")
    if len(user_text) > _MAX_INPUT_CHARS:
        return _result(False, sid, started, user_text=user_text, error=f"文本不能超过 {_MAX_INPUT_CHARS} 字")

    if is_panel_control_command(user_text):
        return _result(
            True,
            sid,
            started,
            user_text=user_text,
            reply_text=_PANEL_COMMAND_REPLY,
            reply_source="panel_command_guard",
            blocked_panel_command=True,
        )

    intent = detect_text_task_intent(user_text)
    if intent.is_task:
        task = build_pending_text_task(intent, user_text)
        reply_text = format_pending_task_reply(task)
        session = session_store.get_or_create(sid)
        session.memory.add_user(user_text)
        session.memory.add_assistant(reply_text, "pending_task")
        return _result(
            True,
            sid,
            started,
            user_text=user_text,
            reply_text=reply_text,
            reply_source="pending_task",
            requires_confirmation=True,
            pending_task=asdict(task),
        )

    app_config = load_config(config_path)
    llm_config = load_llm_provider_config(app_config.llm)
    session = session_store.get_or_create(sid)
    context_text, context_pack = _build_turn_context(
        conversation_id=conversation_id,
        user_text=user_text,
        history_store=history_store,
        legacy_memory_context=session.memory.build_context_text(),
    )

    pipeline_config = ReplyPipelineConfig(
        enable_llm=bool(app_config.llm.enabled),
        enable_tts=False,
        llm_config=llm_config,
        tts_voice=app_config.tts.voice,
        persona=app_config.assistant.persona,
    )

    reply_result = generate_reply_runtime_result(
        user_text,
        config=pipeline_config,
        conversation_context=context_text or None,
        pipeline_func=_generate_text_only_pipeline_result,
    )

    reply_text = str(reply_result.reply_text or "").strip()
    reply_source = str(reply_result.reply_source or "")
    session.memory.add_user(user_text)
    session.memory.add_assistant(reply_text, reply_source)

    return _result(
        True,
        sid,
        started,
        user_text=user_text,
        reply_text=reply_text,
        reply_source=reply_source,
        has_llm_key=bool(llm_config.api_key),
        llm_configured=bool(app_config.llm.enabled and llm_config.is_configured),
        context_pack=context_pack,
    )


def _build_turn_context(
    *,
    conversation_id: str | None,
    user_text: str,
    history_store: Any | None,
    legacy_memory_context: str,
) -> tuple[str, dict | None]:
    if conversation_id and history_store is not None:
        try:
            from xiaohuang.conversation_context_engine import build_context_pack_for_turn

            built = build_context_pack_for_turn(conversation_id, user_text, history_store)
            if built.context_text and built.context_pack is not None:
                return built.context_text, built.context_pack.to_dict()
        except Exception:
            pass
    return legacy_memory_context, None


def _generate_text_only_pipeline_result(
    command_text: str,
    config: ReplyPipelineConfig,
    *,
    on_debug=None,
    conversation_context: str | None = None,
    **_: object,
) -> ReplyPipelineResult:
    if config.enable_llm and config.llm_config is not None:
        from xiaohuang.llm_reply_service import generate_llm_reply_result

        reply_result = generate_llm_reply_result(
            command_text,
            config=config.llm_config,
            on_debug=on_debug,
            persona=config.persona,
            conversation_context=conversation_context,
        )
        return ReplyPipelineResult(
            reply_text=reply_result.text,
            reply_source=reply_result.source,
            source_note=None,
        )

    from xiaohuang.reply_service import generate_reply

    return ReplyPipelineResult(
        reply_text=generate_reply(command_text),
        reply_source="rule",
        source_note=None,
    )


def _result(
    ok: bool,
    session_id: str,
    started: float,
    *,
    user_text: str = "",
    reply_text: str = "",
    reply_source: str = "",
    has_llm_key: bool = False,
    llm_configured: bool = False,
    blocked_panel_command: bool = False,
    requires_confirmation: bool = False,
    pending_task: dict | None = None,
    context_pack: dict | None = None,
    error: str = "",
) -> TextInteractionResult:
    return TextInteractionResult(
        ok=ok,
        session_id=session_id,
        user_text=user_text,
        reply_text=reply_text,
        reply_source=reply_source,
        has_llm_key=has_llm_key,
        llm_configured=llm_configured,
        blocked_panel_command=blocked_panel_command,
        requires_confirmation=requires_confirmation,
        pending_task=pending_task,
        context_pack=context_pack,
        latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
        error=error,
    )
