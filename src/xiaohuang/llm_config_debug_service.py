from __future__ import annotations

import os
from pathlib import Path

from xiaohuang.app_config_service import load_config
from xiaohuang.llm_reply_service import load_llm_provider_config


def build_llm_debug_summary(config_path: Path) -> dict:
    resolved_path = Path(config_path)
    app_config = load_config(resolved_path)
    llm_config = load_llm_provider_config(app_config.llm)
    env_key_name = str(app_config.llm.api_key_env or "").strip()
    env_key_present = bool(env_key_name and os.environ.get(env_key_name))
    api_key_present = bool(llm_config.api_key)
    llm_enabled = bool(app_config.llm.enabled)
    llm_configured = bool(llm_enabled and llm_config.is_configured)

    if not llm_enabled:
        key_source = "llm_disabled"
    elif api_key_present and env_key_name:
        key_source = f"env:{env_key_name}"
    elif env_key_name:
        key_source = f"missing_env:{env_key_name}"
    else:
        key_source = "missing_env_name"

    return {
        "config_path": str(resolved_path),
        "config_exists": resolved_path.exists(),
        "llm_enabled": llm_enabled,
        "llm_configured": llm_configured,
        "provider": llm_config.provider,
        "model": llm_config.model,
        "api_key_present": api_key_present,
        "env_key_name": env_key_name,
        "env_key_present": env_key_present,
        "key_source": key_source,
    }
