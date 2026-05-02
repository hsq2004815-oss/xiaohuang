# XiaoHuang Agent Guide

## Current Phase

This repository is XiaoHuang **V1.1.3A** — User Config Foundation（用户配置中控层）.

The project has evolved from V0.9.1 (minimal single-turn audio pipeline prototype) to V1.1.3A (configurable desktop voice assistant with centralized config layer).

Current pipeline:

```text
config.json / secrets.ps1 → STT server → voice_overlay → wake detection (STT text match) → VAD recording → STT transcription → DeepSeek reply or rule fallback → optional edge-tts → conversation session follow-up
```

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
- `voice_overlay.py`：Tkinter 悬浮窗入口，组装配置链路
- 保持旧 `config_service.load_config`（返回 dict）和新 `app_config_service.load_config`（返回 dataclass）的导入区分
- 禁止两个不同类型变量都叫 `config`

### Config priority

```
CLI explicit args  >  config.json  >  built-in defaults
```

- `store_true` 开关：`_or_config(cli, config)` — True 覆盖 config，False 回退 config
- 标量值：`_coalesce(cli, config)` — 第一个非 None 值生效
- PowerShell：用 `$PSBoundParameters.ContainsKey()` 判断是否显式传参

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

## Hard Boundaries (V1.1.3A)

Do not add these in V1.1.3A:

- LLM Provider Router (multi-provider switching) → V1.1.3B
- Settings UI (graphical config editor) → V1.1.3C
- HUD / system tray / installer → V1.1.4+
- Wake Engine Abstraction (real KWS models) → V1.2
- Multi-turn memory / conversation history persistence
- Tool execution (browser, QQ, WeChat, opencode, opencli, crawlers, file system)
- Offline TTS
- FunASR KWS / openWakeWord training

Current wake is STT text matching, not real KWS. Do not train or add real wake models unless explicitly requested.

Do not modify `E:\DataBase` from this repository work. Database files are read-only context.

## Environment

- Python: `F:\for_xiaohuang\conda310\python.exe`
- Microphone: `device 0`
- Model cache: `F:\for_xiaohuang\models\modelscope`
- STT: FunASR / SenseVoiceSmall
- Dot-source `.\scripts\run_env.ps1` before manual checks
- `run_env.ps1` is a print-only helper; do not change it to auto-record or auto-transcribe

## Git Ignore

Do not commit: `data/recordings/*.wav`, `data/recordings/wake/`, `data/tts/`, `logs/`, `models/`, `.venv/`, `__pycache__/`
