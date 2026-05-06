"""voice_overlay_bootstrap_service.py

Responsibility: load config and assemble all runtime option/config objects
from CLI args. No side effects — no logging, no UI, no threads, no network.

This extracts the "config + path + options assembly" from scripts/voice_overlay.py
so that voice_overlay.py can focus on entry + UI glue + runtime launch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xiaohuang.app_config_service import (
    XiaoHuangConfig,
    apply_cli_overrides,
    load_config as _load_user_config,
)
from xiaohuang.config_service import load_config as _load_legacy_config
from xiaohuang.conversation_session_service import ConversationSessionConfig
from xiaohuang.llm_reply_service import load_llm_provider_config
from xiaohuang.overlay_loop_runtime_service import OverlayLoopRuntimeConfig
from xiaohuang.overlay_runtime_service import resolve_post_response_cooldown
from xiaohuang.reply_pipeline_service import ReplyPipelineConfig
from xiaohuang.wake_loop_service import WakeLoopOptions
from xiaohuang.wake_runtime_service import (
    WakeEngineRuntimeConfig,
    WakeEngineRuntimePlan,
    build_wake_engine_runtime_config,
    select_wake_engine_runtime,
)
from xiaohuang.wake_word_service import parse_wake_phrases


@dataclass(frozen=True)
class VoiceOverlayResolvedPaths:
    project_root: Path
    recording_dir: Path
    tts_output_dir: Path


@dataclass(frozen=True)
class VoiceOverlayBootstrapResult:
    """All config and options needed to launch the voice overlay runtime.

    legacy_config is the YAML-based project defaults (logging, audio, recording).
    app_config is the user-facing JSON config dataclass (wake, llm, tts, etc.).
    """
    legacy_config: dict
    app_config: XiaoHuangConfig
    debug: bool
    enable_llm: bool
    enable_tts: bool
    resident_hidden: bool
    device_id: int
    wake_phrases: list[str]
    wake_aliases: list[str]
    options: WakeLoopOptions
    wake_engine_runtime: WakeEngineRuntimeConfig
    wake_engine_plan: WakeEngineRuntimePlan
    session_config: ConversationSessionConfig
    pipeline_config: ReplyPipelineConfig
    runtime_config: OverlayLoopRuntimeConfig
    post_response_cooldown: float
    paths: VoiceOverlayResolvedPaths


def bootstrap_voice_overlay(
    args,
    *,
    project_root: Path | None = None,
    legacy_config_loader=None,
    user_config_loader=None,
) -> VoiceOverlayBootstrapResult:
    """Load config and build all runtime options from CLI args.

    No side effects. Does not start threads, open windows, or make network calls.
    """
    root = project_root or Path(__file__).resolve().parents[2]

    # ── config loading ──────────────────────────────────────────
    # legacy_config: YAML-based project defaults — logging, audio, recording fallback values.
    # app_config:    JSON-based user runtime config — primary source for wake/llm/tts/etc.
    _load_legacy = legacy_config_loader or _load_legacy_config
    _load_user = user_config_loader or _load_user_config
    legacy_config = _load_legacy()
    app_config = _load_user(args.config, warn=lambda msg: print(f"Config warning: {msg}"))
    app_config = apply_cli_overrides(app_config, args)

    # ── simple flags ────────────────────────────────────────────
    debug = bool(app_config.runtime.debug)
    enable_llm = bool(app_config.llm.enabled)
    enable_tts = bool(app_config.tts.enabled)
    resident_hidden = bool(app_config.overlay.resident_hidden)

    # ── device / paths ──────────────────────────────────────────
    audio_config = legacy_config.get("audio", {})
    recording_config = legacy_config.get("recording", {})

    device_id = args.device
    if device_id is None:
        config_device = audio_config.get("device_id")
        device_id = int(config_device) if config_device is not None else 0

    recording_dir = root / recording_config.get("output_dir", "data/recordings")
    tts_output_dir = root / getattr(args, "tts_output_dir", "data/tts")

    # ── wake ────────────────────────────────────────────────────
    wake_phrases = (
        parse_wake_phrases(args.wake_phrases) if args.wake_phrases
        else app_config.wake.phrases
    )
    wake_aliases = (
        parse_wake_phrases(args.wake_aliases) if args.wake_aliases
        else app_config.wake.aliases
    )

    # ── WakeLoopOptions ─────────────────────────────────────────
    options = WakeLoopOptions(
        device_id=device_id,
        server_url=args.server_url,
        wake_window_seconds=app_config.wake.wake_window_seconds,
        wake_phrases=wake_phrases,
        wake_aliases=wake_aliases,
        max_seconds=app_config.audio.max_seconds,
        silence_seconds=app_config.audio.silence_seconds,
        sample_rate=int(audio_config.get("sample_rate", 16000)),
        channels=int(audio_config.get("channels", 1)),
        recording_dir=recording_dir,
        keep_wake_recordings=False,
    )

    # ── wake engine ─────────────────────────────────────────────
    wake_engine_runtime = build_wake_engine_runtime_config(app_config, options)
    wake_engine_plan = select_wake_engine_runtime(wake_engine_runtime)

    # ── reply / session / runtime config ────────────────────────
    post_response_cooldown = resolve_post_response_cooldown(
        enable_tts, app_config.overlay.post_response_cooldown,
    )
    llm_config = load_llm_provider_config(app_config.llm)

    session_config = ConversationSessionConfig(
        enabled=app_config.conversation.enabled,
        timeout_seconds=app_config.conversation.session_timeout,
        max_turns=app_config.conversation.max_turns,
        followup_timeout_seconds=app_config.conversation.followup_timeout,
        max_session_seconds=app_config.conversation.max_session_seconds,
        max_no_speech_retries=app_config.conversation.max_no_speech_retries,
    )

    pipeline_config = ReplyPipelineConfig(
        enable_llm=enable_llm,
        enable_tts=enable_tts,
        llm_config=llm_config,
        tts_voice=app_config.tts.voice,
        tts_output_dir=tts_output_dir,
        persona=app_config.assistant.persona,
    )

    runtime_config = OverlayLoopRuntimeConfig(
        wake_engine_mode=wake_engine_plan.engine,
        wake_engine_runtime=wake_engine_runtime,
        session_config=session_config,
        enable_tts=enable_tts,
        enable_llm=enable_llm,
        post_response_cooldown=post_response_cooldown,
        resident_hidden=resident_hidden,
        debug=debug,
        assistant_name=app_config.assistant.name,
    )

    paths = VoiceOverlayResolvedPaths(
        project_root=root,
        recording_dir=recording_dir,
        tts_output_dir=tts_output_dir,
    )

    return VoiceOverlayBootstrapResult(
        legacy_config=legacy_config,
        app_config=app_config,
        debug=debug,
        enable_llm=enable_llm,
        enable_tts=enable_tts,
        resident_hidden=resident_hidden,
        device_id=device_id,
        wake_phrases=wake_phrases,
        wake_aliases=wake_aliases,
        options=options,
        wake_engine_runtime=wake_engine_runtime,
        wake_engine_plan=wake_engine_plan,
        session_config=session_config,
        pipeline_config=pipeline_config,
        runtime_config=runtime_config,
        post_response_cooldown=post_response_cooldown,
        paths=paths,
    )
