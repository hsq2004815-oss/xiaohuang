# XiaoHuang Configuration

## File Locations

| File | Path | Purpose |
|------|------|---------|
| config.json | `%USERPROFILE%\.xiaohuang\config.json` | All runtime settings (no API key) |
| secrets.ps1 | `%USERPROFILE%\.xiaohuang\secrets.ps1` | API key only (never committed to Git) |

## Priority

CLI explicit args > config.json > built-in defaults

## Quick Start

```powershell
# Create config dir
New-Item -ItemType Directory -Force "$env:USERPROFILE\.xiaohuang" | Out-Null

# Create/edit config
notepad "$env:USERPROFILE\.xiaohuang\config.json"

# Launch with config
.\scripts\start_xiaohuang.ps1 -EnableLlm -EnableTts -ConfigPath "$env:USERPROFILE\.xiaohuang\config.json"
```

## Example config.json

```json
{
  "wake": {
    "phrases": ["小黄"],
    "aliases": ["小凰", "晓黄"],
    "wake_window_seconds": 3
  },
  "audio": {
    "device_id": 0,
    "max_seconds": 10,
    "silence_seconds": 1
  },
  "llm": {
    "enabled": true,
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "base_url": "https://api.deepseek.com",
    "timeout_seconds": 20,
    "max_tokens": 256,
    "temperature": 0.4,
    "api_key_env": "DEEPSEEK_API_KEY"
  },
  "tts": {
    "enabled": true,
    "voice": "zh-CN-XiaoxiaoNeural"
  },
  "conversation": {
    "enabled": true,
    "followup_timeout": 12,
    "max_turns": 12,
    "max_session_seconds": 300,
    "max_no_speech_retries": 2,
    "session_timeout": 30
  },
  "overlay": {
    "resident_hidden": true
  },
  "runtime": {
    "debug": false
  }
}
```

## Supported Fields

### wake

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| phrases | string[] | `["小黄"]` | Wake phrases |
| aliases | string[] | `[]` | Low-confidence aliases |
| wake_window_seconds | float | 3.0 | Short recording window per wake check |

### audio

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| device_id | int | 0 | Microphone device ID |
| max_seconds | float | 10.0 | Max command recording duration |
| silence_seconds | float | 0.8 | Silence before VAD cutoff |

### llm

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | true | Enable LLM replies |
| provider | string | `"deepseek"` | Provider (placeholder for future multi-provider) |
| model | string | `"deepseek-v4-flash"` | Model name |
| base_url | string | `"https://api.deepseek.com"` | API base URL |
| timeout_seconds | float | 20.0 | Request timeout |
| max_tokens | int | 256 | Max tokens per reply |
| temperature | float | 0.4 | Generation temperature |
| api_key_env | string | `"DEEPSEEK_API_KEY"` | Env var to read API key from (key not stored in config) |

### tts

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | true | Enable TTS |
| voice | string | `"zh-CN-XiaoxiaoNeural"` | edge-tts voice name |

### conversation

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| enabled | bool | true | Enable conversation session |
| followup_timeout | float | 12.0 | Follow-up window after each reply |
| max_turns | int | 12 | Max turns per session |
| max_session_seconds | float | 300.0 | Max session duration |
| max_no_speech_retries | int | 2 | Consecutive no-speech attempts before exit |
| session_timeout | float | 30.0 | Legacy timeout (used as fallback) |

### overlay

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| resident_hidden | bool | true | Start hidden, show on wake |

### runtime

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| debug | bool | false | Print debug output |

## API Key

API key is NOT stored in config.json. Set it via:

- `$env:USERPROFILE\.xiaohuang\secrets.ps1` (recommended)
- Environment variable `DEEPSEEK_API_KEY`

Never commit real keys to Git.

## PowerShell Notes

- `-ConfigPath` tells the launcher where your config file is
- Only `-Device`, `-EnableLlm`, `-EnableTts`, `-Debug`, `-ResidentHidden`, `-ConversationSession` are passed to Python as overrides
- All other params come from config.json or Python defaults
- PS no longer forces default session/wake/tts values over config
