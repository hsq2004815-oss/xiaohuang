# XiaoHuang — CLAUDE.md

## Project Identity

小黄 (XiaoHuang) is a Windows desktop AI voice assistant.  
Current version: **V1.2F** — runtime service extraction phase.

Pipeline: wake detection → command recording → STT transcription → LLM reply / rule fallback → optional edge-tts → conversation session follow-up.

- Entry: `scripts/voice_overlay.py` (Tkinter overlay, ~900 lines, being slimmed)
- Runtime services under `src/xiaohuang/` (wake, command, reply, assistant, session, etc.)
- Config: `app_config_service.py` (dataclass-based), `config.json` in `%USERPROFILE%\.xiaohuang\`
- STT: FunASR SenseVoiceSmall, server at `127.0.0.1:8766`
- LLM: DeepSeek V4 Flash (also supports qwen/doubao/openai_compatible)
- TTS: edge-tts
- Wake engines: `stt_text` (default, text matching) or `openwakeword` (KWS model)
- Python: `F:\for_xiaohuang\conda310\python.exe` (3.10)
- No real API keys in config.json — keys via environment variables / `secrets.ps1`

## Module Boundaries (V1.2F)

| Service | Responsibility |
|---------|---------------|
| `wake_runtime_service.py` | Wake engine selection, openWakeWord listener lifecycle |
| `command_runtime_service.py` | Command recording + STT transcription |
| `reply_runtime_service.py` | Reply pipeline wrapping (LLM/TTS callbacks) |
| `assistant_runtime_service.py` | Turn orchestration, session follow-up loop, single-turn reply handling |
| `llm_reply_service.py` | LLM provider routing, request building, reply extraction |
| `reply_pipeline_service.py` | Rule/LLM fallback chain + TTS synthesis/playback pipeline |
| `openwakeword_adapter.py` | openWakeWord model lifecycle, sounddevice stream, event coalescing |
| `wake_command_bridge_service.py` | WakeEvent → command recorder state machine |
| `wake_engine_service.py` | WakeEvent, Coalescer, Stats, FakeWakeEngine |
| `app_config_service.py` | Config dataclasses, JSON loading, CLI override merging |
| `conversation_session_service.py` | Session exit phrases, turn limits, end reason calculation |
| `launch_control_service.py` | PowerShell process detection, health check, start/stop commands |
| `status_control_service.py` | Control panel status aggregation (~600 lines, under review) |
| `voice_overlay.py` | Tkinter UI + runtime assembly (target: entry + UI only) |

## Code Size and Responsibility Policy

1. 普通 service 文件建议控制在 100–500 行。
2. 超过 500 行时，开发者必须主动检查职责是否开始混合。
3. 超过 600 行时，必须在提交说明中解释为什么暂不拆分，或者拆出独立 service。
4. 超过 900 行时，原则上必须拆分，除非它属于 UI 布局、测试集合、自动生成内容、协议常量集合等特殊文件。
5. 不为了行数机械拆分，只按稳定职责边界拆分。
6. 新功能优先新建独立 service，不继续塞进 `voice_overlay.py`。
7. `voice_overlay.py` 的最终目标是入口 + UI + 运行时组装，不承载 wake / command / reply / session / tool 业务逻辑。
8. 每个 service 只负责一个清晰领域，例如 `wake_runtime`、`command_runtime`、`reply_runtime`、`session_runtime`、`tool_router`、`status_service`。
9. 拆分后必须保持可测试：新 service 要能被单元测试直接调用，不依赖 Tkinter 窗口或真实麦克风。
10. 不允许出现新的"万能 manager / runtime / controller"文件替代 `voice_overlay.py` 变成新的大泥球。

## Pre-commit Architecture Check

Before reporting completion, the agent must check changed Python files:
- If a normal service file exceeds 500 lines, mention it in the report.
- If a normal service file exceeds 600 lines, explain why it is acceptable or propose a split.
- If `voice_overlay.py` grows because of new business logic, stop and propose a separate service instead.
- Tests may be long, but new feature tests should prefer a dedicated `test_*.py` file instead of continuing to grow `test_core_services.py`.

## Verification

```powershell
cd E:\Projects\xiaohuang
$env:PYTHONPATH = "E:\Projects\xiaohuang\src"
& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests
& "F:\for_xiaohuang\conda310\python.exe" -m compileall -q src scripts tests
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --help
```

## API Key and Security

- API key only via `secrets.ps1` / environment variables. `config.json` stores only `api_key_env`.
- Never write API key into: config files, README, logs, code, commit messages.
- `E:\DataBase` is read-only reference context — do not write to it unless explicitly asked.

## Config Priority

```
CLI explicit args  >  config.json  >  built-in defaults
```

- `store_true` switches: `_or_config(cli, config)` — True overrides, False falls back
- Scalar values: `_coalesce(cli, config)` — first non-None wins

## Git Ignore

Do not commit: `data/recordings/*.wav`, `data/recordings/wake/`, `data/tts/`, `logs/`, `models/`, `.venv/`, `__pycache__/`, `.claude/`
