# XiaoHuang Agent Guide

## Current Phase

This repository is XiaoHuang **V1.2F** — runtime service extraction phase.

The project has evolved from V0.9.1 (minimal single-turn audio pipeline prototype) through V1.1.x (config foundation, LLM router, Settings UI, tray launcher, control panel) and V1.2A-E (wake engine abstraction, openWakeWord integration) to V1.2F, which is extracting runtime services from `voice_overlay.py` into focused, testable modules.

Current pipeline:

```text
config.json / secrets.ps1 → STT server → voice_overlay → wake detection (stt_text or openwakeword) → VAD recording → STT transcription → DeepSeek reply or rule fallback → optional edge-tts → conversation session follow-up
```

Extracted runtime services:
- `wake_runtime_service.py` — wake engine selection, openWakeWord listener lifecycle
- `command_runtime_service.py` — command recording + STT transcription
- `reply_runtime_service.py` — reply pipeline wrapping (LLM/TTS callbacks)
- `assistant_runtime_service.py` — turn orchestration, session follow-up loop, single-turn reply handling

`voice_overlay.py` is still being slimmed down toward its final role: entry + UI + runtime assembly only.

## Development Rules

### Scope discipline

- **不要一上来大重构**。先审查当前状态，理解已有模块边界，再做最小改动。
- **不要同时做 LLM Router / Settings UI / HUD / Wake Engine**。这些是不同阶段的任务，不能混在一次改动里。
- **配置层变动必须真实启动 smoke test**。只跑 unittest / compileall / --help 不算完成。必须验证 PowerShell 启动链路、config.json 加载、CLI 覆盖、secrets.ps1 加载。
- **修改 PowerShell 脚本后必须真实运行**，不能只看语法。

### API key and security

- **API key 只允许走 secrets.ps1 / 环境变量**。`config.json` 只存 `api_key_env` 环境变量名，不存真实 key。
- **不允许把 API key 写入**：配置文件、README、日志、代码、commit message。
- **不允许写 E:\DataBase**，除非用户明确要求维护数据库。数据库文件是只读参考上下文。

### Module boundaries

- `app_config_service.py`：配置中控层，`XiaoHuangConfig` dataclass，`load_config` / `merge_config_dict` / `apply_cli_overrides`
- `llm_reply_service.py`：LLM 请求构建和回复生成，接收可选 `persona` 参数
- `reply_pipeline_service.py`：回复管道编排
- `voice_overlay.py`：Tkinter 悬浮窗入口，组装配置链路（最终目标：入口 + UI + 运行时组装）
- `wake_runtime_service.py`：唤醒引擎选择 + openWakeWord listener 生命周期
- `command_runtime_service.py`：命令录音 + STT 转写
- `reply_runtime_service.py`：reply pipeline + TTS 回调包装
- `assistant_runtime_service.py`：turn 编排 + session follow-up loop
- 保持旧 `config_service.load_config`（返回 dict）和新 `app_config_service.load_config`（返回 dataclass）的导入区分
- 禁止两个不同类型变量都叫 `config`

### Config priority

```
CLI explicit args  >  config.json  >  built-in defaults
```

- `store_true` 开关：`_or_config(cli, config)` — True 覆盖 config，False 回退 config
- 标量值：`_coalesce(cli, config)` — 第一个非 None 值生效
- PowerShell：用 `$PSBoundParameters.ContainsKey()` 判断是否显式传参

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

## Hard Boundaries

Do not add these:

- Multi-turn memory / conversation history persistence
- Tool execution (browser, QQ, WeChat, opencode, opencli, crawlers, file system)
- Offline TTS
- FunASR KWS / openWakeWord Chinese "贾维斯" model training
- No new "god object" manager/runtime/controller to replace `voice_overlay.py`

Already completed and should not be re-done from scratch:
- LLM Provider Router (deepseek/qwen/doubao/openai_compatible) — V1.1.3B ✅
- Settings UI (graphical config editor) — V1.1.3C ✅
- System tray / launch control — V1.1.4 ✅
- Wake Engine Abstraction + openWakeWord integration — V1.2A-E ✅
- Status control panel — V1.1.4D ✅

## Verification

Run these before reporting completion:

```powershell
cd E:\Projects\xiaohuang
. .\scripts\run_env.ps1
& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests
& "F:\for_xiaohuang\conda310\python.exe" -m compileall -q src scripts tests
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --help
```

For config-layer changes, also run real smoke tests that verify:

- config.json loads and overrides defaults
- PowerShell scripts don't override config with default values
- CLI flags only override when explicitly passed
- API key is not stored in config dataclass
- Persona flows through to LLM request builder

## Environment

- Python: `F:\for_xiaohuang\conda310\python.exe`
- Microphone: `device 0`
- Model cache: `F:\for_xiaohuang\models\modelscope`
- STT: FunASR / SenseVoiceSmall
- Dot-source `.\scripts\run_env.ps1` before manual checks
- `run_env.ps1` is a print-only helper; do not change it to auto-record or auto-transcribe

## Git Ignore

Do not commit: `data/recordings/*.wav`, `data/recordings/wake/`, `data/tts/`, `logs/`, `models/`, `.venv/`, `__pycache__/`
