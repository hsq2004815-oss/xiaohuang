from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class WakeConfig:
    engine: str = "stt_text"
    phrases: list[str] = field(default_factory=lambda: ["小黄"])
    aliases: list[str] = field(default_factory=list)
    wake_window_seconds: float = 3.0
    fallback_enabled: bool = True
    sensitivity: float = 0.5
    cooldown_seconds: float = 2.5
    device_index: int | None = None
    model_path: str | None = None
    model_name: str | None = None
    wake_greeting_enabled: bool = False
    wake_greeting_text: str = "您好先生，有什么为你服务？"


@dataclass(frozen=True)
class AudioConfig:
    device_id: int = 0
    max_seconds: float = 10.0
    silence_seconds: float = 0.8


@dataclass(frozen=True)
class SttConfig:
    engine: str = "funasr"
    model_name: str = "iic/SenseVoiceSmall"
    language: str = "auto"
    use_itn: bool = True
    device: str = "cpu"


@dataclass(frozen=True)
class LlmConfig:
    enabled: bool = True
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    timeout_seconds: float = 20.0
    max_tokens: int = 256
    temperature: float = 0.4
    api_key_env: str = "DEEPSEEK_API_KEY"


@dataclass(frozen=True)
class TtsConfig:
    enabled: bool = True
    voice: str = "zh-CN-XiaoxiaoNeural"
    output_dir: str | None = None


@dataclass(frozen=True)
class ConversationConfig:
    enabled: bool = True
    followup_timeout: float = 12.0
    max_turns: int = 12
    max_session_seconds: float = 300.0
    max_no_speech_retries: int = 2
    session_timeout: float = 30.0


@dataclass(frozen=True)
class OverlayConfig:
    resident_hidden: bool = True
    post_response_cooldown: float | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    debug: bool = False


_DEFAULT_PERSONA = (
    "你是小黄，一个友好、简洁、可靠的 Windows 桌面语音助手。"
    "回答要自然、简短，适合语音播报。"
)


@dataclass(frozen=True)
class AssistantConfig:
    name: str = "小黄"
    display_name: str = "小黄"
    persona: str = _DEFAULT_PERSONA


@dataclass(frozen=True)
class XiaoHuangConfig:
    wake: WakeConfig = field(default_factory=WakeConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    stt: SttConfig = field(default_factory=SttConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    conversation: ConversationConfig = field(default_factory=ConversationConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    assistant: AssistantConfig = field(default_factory=AssistantConfig)


def get_default_config() -> XiaoHuangConfig:
    return XiaoHuangConfig()


def get_default_config_path() -> Path:
    return Path.home() / ".xiaohuang" / "config.json"


def load_config(
    path: str | Path | None = None,
    *,
    warn: Callable[[str], None] | None = None,
) -> XiaoHuangConfig:
    resolved = Path(path) if path else get_default_config_path()
    if not resolved.exists():
        return get_default_config()
    try:
        text = resolved.read_text(encoding="utf-8")
    except Exception as exc:
        _emit_warn(warn, f"Cannot read config file {resolved}: {exc}")
        return get_default_config()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        _emit_warn(warn, f"Invalid JSON in config file {resolved}: {exc}")
        return get_default_config()
    if not isinstance(data, dict):
        _emit_warn(warn, f"Config root must be a JSON object, got {type(data).__name__}")
        return get_default_config()
    return merge_config_dict(get_default_config(), data, warn=warn)


def merge_config_dict(
    base: XiaoHuangConfig,
    data: dict[str, Any],
    *,
    warn: Callable[[str], None] | None = None,
) -> XiaoHuangConfig:
    sections: dict[str, Any] = {}
    for section_name, section_value in data.items():
        if not isinstance(section_value, dict):
            _emit_warn(warn, f"Config section '{section_name}' must be an object, skipping")
            continue
        sections[section_name] = section_value

    return XiaoHuangConfig(
        wake=_merge_wake(base.wake, sections.get("wake", {}), warn=warn),
        audio=_merge_audio(base.audio, sections.get("audio", {}), warn=warn),
        stt=_merge_stt(base.stt, sections.get("stt", {}), warn=warn),
        llm=_merge_llm(base.llm, sections.get("llm", {}), warn=warn),
        tts=_merge_tts(base.tts, sections.get("tts", {}), warn=warn),
        conversation=_merge_conversation(base.conversation, sections.get("conversation", {}), warn=warn),
        overlay=_merge_overlay(base.overlay, sections.get("overlay", {}), warn=warn),
        runtime=_merge_runtime(base.runtime, sections.get("runtime", {}), warn=warn),
        assistant=_merge_assistant(base.assistant, sections.get("assistant", {}), warn=warn),
    )


def apply_cli_overrides(
    config: XiaoHuangConfig,
    args: Any,
) -> XiaoHuangConfig:
    return XiaoHuangConfig(
        wake=WakeConfig(
            engine=config.wake.engine,
            phrases=config.wake.phrases,
            aliases=config.wake.aliases,
            wake_window_seconds=_coalesce(args.wake_window_seconds, config.wake.wake_window_seconds),
            fallback_enabled=config.wake.fallback_enabled,
            sensitivity=config.wake.sensitivity,
            cooldown_seconds=config.wake.cooldown_seconds,
            device_index=config.wake.device_index,
            model_path=config.wake.model_path,
            model_name=config.wake.model_name,
            wake_greeting_enabled=_or_config(
                getattr(args, "wake_greeting", None), config.wake.wake_greeting_enabled,
            ),
            wake_greeting_text=_coalesce(
                getattr(args, "wake_greeting_text", None), config.wake.wake_greeting_text,
            ),
        ),
        audio=AudioConfig(
            device_id=_coalesce(args.device, config.audio.device_id),
            max_seconds=_coalesce(args.max_seconds, config.audio.max_seconds),
            silence_seconds=_coalesce(args.silence_seconds, config.audio.silence_seconds),
        ),
        stt=config.stt,
        llm=LlmConfig(
            enabled=_or_config(args.enable_llm, config.llm.enabled),
            provider=config.llm.provider,
            model=_coalesce(args.llm_model, config.llm.model),
            base_url=_coalesce(args.llm_base_url, config.llm.base_url),
            timeout_seconds=_coalesce(args.llm_timeout, config.llm.timeout_seconds),
            max_tokens=_coalesce(args.llm_max_tokens, config.llm.max_tokens),
            temperature=config.llm.temperature,
            api_key_env=config.llm.api_key_env,
        ),
        tts=TtsConfig(
            enabled=_or_config(args.enable_tts, config.tts.enabled),
            voice=_coalesce(args.tts_voice, config.tts.voice),
            output_dir=_coalesce(args.tts_output_dir, config.tts.output_dir),
        ),
        conversation=ConversationConfig(
            enabled=_or_config(args.conversation_session, config.conversation.enabled),
            followup_timeout=_coalesce(args.followup_timeout, config.conversation.followup_timeout),
            max_turns=_coalesce(args.max_session_turns, config.conversation.max_turns),
            max_session_seconds=_coalesce(args.max_session_seconds, config.conversation.max_session_seconds),
            max_no_speech_retries=_coalesce(args.max_no_speech_retries, config.conversation.max_no_speech_retries),
            session_timeout=_coalesce(args.session_timeout, config.conversation.session_timeout),
        ),
        overlay=OverlayConfig(
            resident_hidden=_or_config(args.resident_hidden, config.overlay.resident_hidden),
            post_response_cooldown=_coalesce(args.post_response_cooldown, config.overlay.post_response_cooldown),
        ),
        runtime=RuntimeConfig(
            debug=_or_config(args.debug, config.runtime.debug),
        ),
        assistant=config.assistant,
    )


# ---------------------------------------------------------------------------
# section mergers
# ---------------------------------------------------------------------------

def _merge_wake(base: WakeConfig, data: dict[str, Any], *, warn=None) -> WakeConfig:
    phrases = _coerce_phrases(data.get("phrases"), warn=warn)
    engine = data.get("engine")
    return WakeConfig(
        engine=str(engine).strip().lower() if engine is not None and str(engine).strip() else base.engine,
        phrases=phrases if phrases else base.phrases,
        aliases=_coerce_aliases(data.get("aliases"), warn=warn),
        wake_window_seconds=_coerce_float(data.get("wake_window_seconds"), base.wake_window_seconds, 0.5, 30.0, warn),
        fallback_enabled=_coerce_bool(data.get("fallback_enabled"), base.fallback_enabled, warn),
        sensitivity=_coerce_float(data.get("sensitivity"), base.sensitivity, 0.0, 1.0, warn),
        cooldown_seconds=_coerce_float(data.get("cooldown_seconds"), base.cooldown_seconds, 0.0, 30.0, warn),
        device_index=_coerce_optional_int(data.get("device_index"), base.device_index, 0, 99, warn),
        model_path=_coerce_optional_str(data.get("model_path"), base.model_path),
        model_name=_coerce_optional_str(data.get("model_name"), base.model_name),
        wake_greeting_enabled=_coerce_bool(data.get("wake_greeting_enabled"), base.wake_greeting_enabled, warn),
        wake_greeting_text=_coerce_str(data.get("wake_greeting_text"), base.wake_greeting_text),
    )


def _merge_audio(base: AudioConfig, data: dict[str, Any], *, warn=None) -> AudioConfig:
    return AudioConfig(
        device_id=_coerce_int(data.get("device_id"), base.device_id, 0, 99, warn),
        max_seconds=_coerce_float(data.get("max_seconds"), base.max_seconds, 1.0, 120.0, warn),
        silence_seconds=_coerce_float(data.get("silence_seconds"), base.silence_seconds, 0.1, 10.0, warn),
    )


def _merge_stt(base: SttConfig, data: dict[str, Any], *, warn=None) -> SttConfig:
    return SttConfig(
        engine=_coerce_str(data.get("engine"), base.engine),
        model_name=_coerce_str(data.get("model_name"), base.model_name),
        language=_coerce_str(data.get("language"), base.language),
        use_itn=_coerce_bool(data.get("use_itn"), base.use_itn, warn),
        device=_coerce_str(data.get("device"), base.device).lower(),
    )


def _merge_llm(base: LlmConfig, data: dict[str, Any], *, warn=None) -> LlmConfig:
    return LlmConfig(
        enabled=_coerce_bool(data.get("enabled"), base.enabled, warn),
        provider=str(data.get("provider", base.provider)),
        model=str(data.get("model", base.model)),
        base_url=str(data.get("base_url", base.base_url)),
        timeout_seconds=_coerce_float(data.get("timeout_seconds"), base.timeout_seconds, 1.0, 300.0, warn),
        max_tokens=_coerce_int(data.get("max_tokens"), base.max_tokens, 1, 16384, warn),
        temperature=_coerce_float(data.get("temperature"), base.temperature, 0.0, 2.0, warn),
        api_key_env=str(data.get("api_key_env", base.api_key_env)),
    )


def _merge_tts(base: TtsConfig, data: dict[str, Any], *, warn=None) -> TtsConfig:
    voice = data.get("voice")
    output_dir = data.get("output_dir")
    return TtsConfig(
        enabled=_coerce_bool(data.get("enabled"), base.enabled, warn),
        voice=str(voice) if voice is not None else base.voice,
        output_dir=str(output_dir) if output_dir is not None else base.output_dir,
    )


def _merge_conversation(base: ConversationConfig, data: dict[str, Any], *, warn=None) -> ConversationConfig:
    return ConversationConfig(
        enabled=_coerce_bool(data.get("enabled"), base.enabled, warn),
        followup_timeout=_coerce_float(data.get("followup_timeout"), base.followup_timeout, 1.0, 300.0, warn),
        max_turns=_coerce_int(data.get("max_turns"), base.max_turns, 1, 999, warn),
        max_session_seconds=_coerce_float(data.get("max_session_seconds"), base.max_session_seconds, 10.0, 86400.0, warn),
        max_no_speech_retries=_coerce_int(data.get("max_no_speech_retries"), base.max_no_speech_retries, 0, 99, warn),
        session_timeout=_coerce_float(data.get("session_timeout"), base.session_timeout, 1.0, 300.0, warn),
    )


def _merge_overlay(base: OverlayConfig, data: dict[str, Any], *, warn=None) -> OverlayConfig:
    cooldown = data.get("post_response_cooldown")
    return OverlayConfig(
        resident_hidden=_coerce_bool(data.get("resident_hidden"), base.resident_hidden, warn),
        post_response_cooldown=float(cooldown) if cooldown is not None else base.post_response_cooldown,
    )


def _merge_runtime(base: RuntimeConfig, data: dict[str, Any], *, warn=None) -> RuntimeConfig:
    return RuntimeConfig(
        debug=_coerce_bool(data.get("debug"), base.debug, warn),
    )


def _merge_assistant(base: AssistantConfig, data: dict[str, Any], *, warn=None) -> AssistantConfig:
    name = data.get("name")
    display_name = data.get("display_name")
    persona = data.get("persona")
    return AssistantConfig(
        name=str(name).strip() if isinstance(name, str) and name.strip() else base.name,
        display_name=str(display_name).strip() if isinstance(display_name, str) and display_name.strip() else base.display_name,
        persona=str(persona).strip() if isinstance(persona, str) and persona.strip() else base.persona,
    )


# ---------------------------------------------------------------------------
# coercion helpers
# ---------------------------------------------------------------------------

def _coerce_phrases(value: Any, *, warn=None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value.strip()] if value.strip() else None
    if isinstance(value, list):
        result = [str(v).strip() for v in value if str(v).strip()]
        return result if result else None
    _emit_warn(warn, f"wake.phrases must be string or list, got {type(value).__name__}")
    return None


def _coerce_aliases(value: Any, *, warn=None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    _emit_warn(warn, f"wake.aliases must be string or list")
    return []


def _coerce_int(value: Any, default: int, lo: int, hi: int, warn=None) -> int:
    try:
        v = int(value)
        if lo <= v <= hi:
            return v
    except (TypeError, ValueError):
        pass
    if warn:
        warn(f"Expected int in [{lo},{hi}], using default {default}")
    return default


def _coerce_optional_int(value: Any, default: int | None, lo: int, hi: int, warn=None) -> int | None:
    if value is None:
        return default
    try:
        v = int(value)
        if lo <= v <= hi:
            return v
    except (TypeError, ValueError):
        pass
    if warn:
        warn(f"Expected int in [{lo},{hi}], using default {default}")
    return default


def _coerce_float(value: Any, default: float, lo: float, hi: float, warn=None) -> float:
    try:
        v = float(value)
        if lo <= v <= hi:
            return v
    except (TypeError, ValueError):
        pass
    if warn:
        warn(f"Expected float in [{lo},{hi}], using default {default}")
    return default


def _coerce_optional_str(value: Any, default: str | None) -> str | None:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _coerce_str(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _coerce_bool(value: Any, default: bool, warn=None) -> bool:
    if isinstance(value, bool):
        return value
    if warn and value is not None:
        warn(f"Expected boolean, using default {default}")
    return default


def _or_config(cli_value: Any, config_value: bool) -> bool:
    """For store_true args: only True from CLI overrides config; False means 'not passed'."""
    if cli_value is True:
        return True
    return config_value


def _coalesce(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def _emit_warn(warn: Callable[[str], None] | None, msg: str) -> None:
    if warn:
        warn(msg)
