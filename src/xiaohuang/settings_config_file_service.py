from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xiaohuang.app_config_service import get_default_config, load_config as load_user_config

_VALID_PROVIDERS = {"deepseek", "qwen", "doubao", "openai_compatible"}

_KNOWN_SECTIONS: dict[str, list[str]] = {
    "wake": ["phrases", "aliases", "wake_window_seconds"],
    "audio": ["device_id", "max_seconds", "silence_seconds"],
    "llm": [
        "enabled", "provider", "model", "base_url",
        "api_key_env", "timeout_seconds", "max_tokens", "temperature",
    ],
    "tts": ["enabled", "voice"],
    "conversation": [
        "enabled", "followup_timeout", "max_turns",
        "max_session_seconds", "max_no_speech_retries", "session_timeout",
    ],
    "overlay": ["resident_hidden", "post_response_cooldown"],
    "runtime": ["debug"],
    "assistant": ["name", "display_name", "persona"],
}

_FIELD_VALIDATORS: dict[str, dict[str, Any]] = {
    "wake": {
        "wake_window_seconds": {"type": "float", "lo": 0.5, "hi": 30.0},
    },
    "audio": {
        "device_id": {"type": "int", "lo": 0, "hi": 99},
        "max_seconds": {"type": "float", "lo": 1.0, "hi": 120.0},
        "silence_seconds": {"type": "float", "lo": 0.1, "hi": 10.0},
    },
    "llm": {
        "timeout_seconds": {"type": "float", "lo": 1.0, "hi": 300.0},
        "max_tokens": {"type": "int", "lo": 1, "hi": 16384},
        "temperature": {"type": "float", "lo": 0.0, "hi": 2.0},
    },
    "conversation": {
        "followup_timeout": {"type": "float", "lo": 1.0, "hi": 300.0},
        "max_turns": {"type": "int", "lo": 1, "hi": 999},
        "max_session_seconds": {"type": "float", "lo": 10.0, "hi": 86400.0},
        "max_no_speech_retries": {"type": "int", "lo": 0, "hi": 99},
        "session_timeout": {"type": "float", "lo": 1.0, "hi": 300.0},
    },
}


@dataclass
class ConfigValidationResult:
    valid: bool = True
    errors: list[str] = field(default_factory=list)


def load_config_with_unknown(path: str | Path) -> tuple[dict[str, Any], str | None]:
    """Load config JSON and also return unknown fields.

    Returns (known_data, error_message).
    known_data includes all fields from the file, preserving unknown sections/keys.
    """
    resolved = Path(path)
    if not resolved.exists():
        default = get_default_config()
        return _dataclass_to_sections(default), None
    try:
        text = resolved.read_text(encoding="utf-8")
    except Exception as exc:
        return {}, f"Cannot read config file: {exc}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"Invalid JSON: {exc}"
    if not isinstance(data, dict):
        return {}, f"Config root must be a JSON object"
    return data, None


def normalize_ui_inputs(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize UI input data to proper types for saving.

    - Converts comma/Chinese-comma/newline-separated strings to lists
    - Validates number ranges
    - Checks api_key_env doesn't look like a real key
    - Returns (normalized_data, errors_list)
    """
    result: dict[str, Any] = {}
    errors: list[str] = []

    for section_name, section_value in data.items():
        if not isinstance(section_value, dict):
            result[section_name] = section_value
            continue
        result[section_name] = {}
        for key, value in section_value.items():
            normalized, err = _normalize_field(section_name, key, value)
            if err:
                errors.append(f"[{section_name}].{key}: {err}")
            else:
                result[section_name][key] = normalized

    return result, errors


def validate_config(data: dict[str, Any]) -> ConfigValidationResult:
    """Validate config data before saving."""
    result = ConfigValidationResult()

    # wake.phrases must not be empty
    wake = data.get("wake", {})
    if isinstance(wake, dict):
        phrases = wake.get("phrases")
        if isinstance(phrases, list) and not phrases:
            result.valid = False
            result.errors.append("wake.phrases 不能为空")
        if isinstance(phrases, list) and len(phrases) == 1 and not str(phrases[0]).strip():
            result.valid = False
            result.errors.append("wake.phrases 不能为空字符串")

    # llm.provider validation
    llm = data.get("llm", {})
    if isinstance(llm, dict):
        provider = llm.get("provider")
        if isinstance(provider, str) and provider.strip():
            if provider.strip() not in _VALID_PROVIDERS:
                result.valid = False
                result.errors.append(
                    f"llm.provider 值无效：'{provider}'，"
                    f"允许的值：{', '.join(sorted(_VALID_PROVIDERS))}"
                )

    # api_key_env must not look like a real API key
    if isinstance(llm, dict):
        api_key_env = llm.get("api_key_env")
        if isinstance(api_key_env, str) and _looks_like_api_key(api_key_env.strip()):
            result.valid = False
            result.errors.append(
                "llm.api_key_env 疑似真实 API key。请填写环境变量名（如 DEEPSEEK_API_KEY），"
                "真实 key 请放在 secrets.ps1"
            )

    return result


def save_config(
    path: str | Path,
    data: dict[str, Any],
    original_data: dict[str, Any] | None = None,
) -> str | None:
    """Save config data to JSON file, preserving unknown fields from original.

    Returns error message string on failure, None on success.
    """
    resolved = Path(path)

    # Merge: keep unknown sections/keys from original
    merged: dict[str, Any] = {}
    if original_data:
        merged = _deep_copy_dict(original_data)
        # Overlay known sections with new data
        for section_name, section_value in data.items():
            if isinstance(section_value, dict) and isinstance(merged.get(section_name), dict):
                existing = dict(merged[section_name])
                existing.update(section_value)
                merged[section_name] = existing
            else:
                merged[section_name] = section_value
    else:
        merged = data

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(merged, indent=2, ensure_ascii=False)
        resolved.write_text(text + "\n", encoding="utf-8")
    except Exception as exc:
        return f"保存失败：{exc}"
    return None


def _dataclass_to_sections(cfg: Any) -> dict[str, Any]:
    """Convert a XiaoHuangConfig to a dict of sections for UI display."""
    return {
        "wake": {
            "phrases": _join_list(cfg.wake.phrases),
            "aliases": _join_list(cfg.wake.aliases),
            "wake_window_seconds": cfg.wake.wake_window_seconds,
        },
        "audio": {
            "device_id": cfg.audio.device_id,
            "max_seconds": cfg.audio.max_seconds,
            "silence_seconds": cfg.audio.silence_seconds,
        },
        "llm": {
            "enabled": cfg.llm.enabled,
            "provider": cfg.llm.provider,
            "model": cfg.llm.model,
            "base_url": cfg.llm.base_url,
            "api_key_env": cfg.llm.api_key_env,
            "timeout_seconds": cfg.llm.timeout_seconds,
            "max_tokens": cfg.llm.max_tokens,
            "temperature": cfg.llm.temperature,
        },
        "tts": {
            "enabled": cfg.tts.enabled,
            "voice": cfg.tts.voice,
        },
        "conversation": {
            "enabled": cfg.conversation.enabled,
            "followup_timeout": cfg.conversation.followup_timeout,
            "max_turns": cfg.conversation.max_turns,
            "max_session_seconds": cfg.conversation.max_session_seconds,
            "max_no_speech_retries": cfg.conversation.max_no_speech_retries,
            "session_timeout": cfg.conversation.session_timeout,
        },
        "overlay": {
            "resident_hidden": cfg.overlay.resident_hidden,
            "post_response_cooldown": cfg.overlay.post_response_cooldown,
        },
        "runtime": {
            "debug": cfg.runtime.debug,
        },
        "assistant": {
            "name": cfg.assistant.name,
            "display_name": cfg.assistant.display_name,
            "persona": cfg.assistant.persona,
        },
    }


def _join_list(items: list[str]) -> str:
    return ", ".join(str(v) for v in items)


def _normalize_field(section: str, key: str, value: Any) -> tuple[Any, str | None]:
    """Normalize a single field value. Returns (normalized_value, error_message)."""
    section_validators = _FIELD_VALIDATORS.get(section, {})
    validator = section_validators.get(key)

    # List fields: parse comma-separated
    if section == "wake" and key in ("phrases", "aliases"):
        items = _parse_list(value)
        if key == "phrases" and not items:
            return None, "不能为空"
        return items, None

    # Bool fields
    if key == "enabled" or key == "resident_hidden" or key == "debug":
        if isinstance(value, bool):
            return value, None
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        return bool(value), None

    # Optional numeric fields: blank means "automatic/default".
    if section == "overlay" and key == "post_response_cooldown":
        if value is None:
            return None, None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped.lower() in ("none", "null"):
                return None, None
            value = stripped
        return _validate_number(value, "float", 0.0, 3600.0)

    # provider validation
    if section == "llm" and key == "provider":
        if isinstance(value, str) and value.strip():
            p = value.strip()
            if p not in _VALID_PROVIDERS:
                return p, f"无效值 '{p}'，允许：{', '.join(sorted(_VALID_PROVIDERS))}"
            return p, None
        return value, None

    # api_key_env: detect real key patterns
    if section == "llm" and key == "api_key_env":
        if isinstance(value, str) and _looks_like_api_key(value.strip()):
            return value, "疑似真实 API key，请填写环境变量名"
        return str(value).strip() if isinstance(value, str) else str(value), None

    # Number validation
    if validator:
        return _validate_number(value, validator["type"], validator["lo"], validator["hi"])

    # String / passthrough
    if value is None:
        return value, None
    return value, None


def _parse_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
        return items
    if isinstance(value, str):
        # Split on comma, Chinese comma, newline
        import re
        parts = re.split(r"[，,\n]", value)
        items = [p.strip() for p in parts if p.strip()]
        return items
    return []


def _validate_number(value: Any, num_type: str, lo: float, hi: float) -> tuple[Any, str | None]:
    try:
        if num_type == "int":
            v = int(value)
            if lo <= v <= hi:
                return v, None
            return value, f"应在 [{int(lo)}, {int(hi)}] 范围内"
        v = float(value)
        if lo <= v <= hi:
            return v, None
        return value, f"应在 [{lo}, {hi}] 范围内"
    except (TypeError, ValueError):
        return value, f"需要是{'整数' if num_type == 'int' else '数字'}"


def _looks_like_api_key(value: str) -> bool:
    """Heuristic: does this string look like an API key rather than an env var name?"""
    v = value.strip()
    # Env var names are typically UPPER_SNAKE_CASE, short
    if len(v) < 5:
        return False
    # Real keys typically start with sk- or contain long random chars
    if v.lower().startswith("sk-"):
        return True
    # Very long strings are suspicious (env var names are rarely > 50 chars)
    if len(v) > 50:
        return True
    # Contains spaces → likely not an env var name
    if " " in v:
        return True
    # Looks like a typical API key pattern (long random string)
    if len(v) > 30 and not v.isupper() and not v.startswith("$"):
        return True
    return False


def _deep_copy_dict(d: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(d, ensure_ascii=False))
