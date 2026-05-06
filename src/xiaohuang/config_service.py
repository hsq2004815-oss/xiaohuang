from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "dtype": "int16",
        "device_id": None,
    },
    "recording": {
        "duration_seconds": 5,
        "output_dir": "data/recordings",
    },
    "stt": {
        "engine": "funasr",
        "model_name": "iic/SenseVoiceSmall",
        "language": "zh",
        "use_itn": True,
        "device": "cpu",
    },
    "logging": {
        "directory": "logs",
        "level": "INFO",
    },
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    return project_root() / "config" / "xiaohuang.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else default_config_path()
    if not config_path.exists():
        return dict(DEFAULT_CONFIG)

    text = config_path.read_text(encoding="utf-8")
    loaded = _parse_yaml(text)
    return _deep_merge(DEFAULT_CONFIG, loaded)


def _parse_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        return _parse_simple_yaml(text)

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("Configuration root must be a mapping.")
    return data


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_section: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line:
            continue
        if not line.startswith(" "):
            key = line.rstrip(":")
            result[key] = {}
            current_section = key
            continue
        if current_section is None or ":" not in line:
            continue
        key, value = line.strip().split(":", 1)
        result[current_section][key] = _coerce_scalar(value.strip())

    return result


def _coerce_scalar(value: str) -> Any:
    if value in {"", "null", "None"}:
        return None
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    try:
        return int(value)
    except ValueError:
        return value.strip('"').strip("'")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = {key: value.copy() if isinstance(value, dict) else value for key, value in base.items()}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
