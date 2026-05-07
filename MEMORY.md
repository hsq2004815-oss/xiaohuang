# XiaoHuang Memory

- Project: `E:\Projects\xiaohuang`
- Repository: `hsq2004815-oss/xiaohuang`
- Local branch: `main`
- Current stable version: V1.4-A Capability Router MVP, code + docs + human validation passed.
- Current milestone commit: `9c39dd1 feat: add safe capability router MVP`
- V1.4-A acceptance doc: `docs/v1.4a-capability-router-acceptance.md`
- Recommended final tag: `v1.4a-capability-router-accepted`
- Current status after V1.4-A: local working tree clean, `origin/main` synced after `9c39dd1`.
- Current goal: close V1.4-A as a stable baseline, then start V1.4-B Conversation Session Memory / short-term multi-turn context.

## Current V1.4-A Summary

XiaoHuang has moved from a voice chat assistant prototype into a Windows desktop assistant with a safe whitelisted capability layer.

V1.4-A added a deterministic Capability Router / Local Command Router. It does not use LLM function calling yet. It uses explicit Chinese keyword matching and executes only safe allowlisted local capabilities.

Implemented safe capabilities:

- `open_logs_folder`
  - Opens only the project `logs/` directory.
  - Does not accept arbitrary user paths.

- `run_preflight_check`
  - Reuses existing preflight check capability.
  - Runs environment/startup checks.

- `get_status`
  - Reads current XiaoHuang runtime/control-panel status.
  - Read-only. Does not start or stop processes.

- `export_diagnostics`
  - Reuses existing diagnostic export logic.
  - Exports diagnostic text under project logs flow.

- `open_control_panel`
  - Opens fixed script `scripts/control_panel_web.py`.
  - Uses `subprocess.Popen([...])` with list args.
  - No `shell=True`.
  - Passes safe environment:
    - `PYTHONPATH = <project_root>\src`
    - `PYTHONUTF8 = 1`
    - `PYTHONIOENCODING = utf-8`

## V1.4-A Safety Boundary

The capability layer is intentionally conservative.

Rejected / unsupported in V1.4-A:

- arbitrary shell / PowerShell / cmd execution
- user-provided command execution
- file deletion or file editing
- arbitrary path opening
- browser automation
- WeChat / QQ automation
- downloader / crawler / task scheduler
- letting DeepSeek execute system commands

Safety principles:

- fail closed
- deny high-risk keywords first
- all side effects must go through explicit whitelisted handlers
- ordinary chat must not trigger local side effects
- tool-like requests outside the whitelist must be rejected without calling the LLM
- dangerous requests must return a human-readable refusal
- runtime events must not include API keys, tokens, passwords, secrets, or authorization values

## Capability Router Integration

Main integration point:

- `src/xiaohuang/reply_pipeline_service.py`

Current flow:

1. User speech is transcribed into command text.
2. `reply_pipeline_service` calls the capability route before ordinary LLM/rule reply.
3. If a safe whitelisted capability matches:
   - execute handler
   - return source similar to capability result
   - do not call LLM
   - optional TTS still follows existing flow
4. If the text is a tool request but not allowlisted:
   - return refusal
   - do not call LLM
   - optional TTS still follows existing flow
5. If it is ordinary chat:
   - continue the previous LLM / rule fallback behavior

Important preserved behavior:

- DeepSeek key configured -> LLM may run normally.
- DeepSeek key missing -> fallback source stays `rule_fallback_no_key`.
- LLM failure -> fallback to local rule reply.
- Capability Router must not break ordinary chat.

## Runtime Events

Capability execution records runtime events through the existing runtime event service.

Event source:

- `capability_router`

Known event types:

- `capability_invoked`
- `capability_completed`
- `capability_failed`

Event recording must be warning-only. Failure to write runtime events must not crash the main voice/reply flow.

## V1.4-A Validation

Automated validation passed:

- `compileall -q src scripts tests` -> OK
- `tests.test_capability_router` -> 37 tests OK
- `test_fallback_no_key_preserved` -> OK after test environment isolation fix
- `unittest discover -s tests` -> 704 tests OK
- `voice_overlay.py --help` -> OK
- `control_panel_web.py --help` -> OK
- `stt_server.py --help` -> OK

Important test isolation fix:

- `tests/test_llm_reply_service.py`
- `test_fallback_no_key_preserved` now temporarily clears and restores:
  - `DEEPSEEK_API_KEY`
  - `DEEPSEEK_BASE_URL`
  - `DEEPSEEK_MODEL`
  - `DEEPSEEK_MAX_TOKENS`
- This fix only isolates test environment behavior.
- It does not change real business logic.

Manual Chinese route validation passed:

- `打开日志目录` -> `open_logs_folder`
- `运行启动前检查` -> `run_preflight_check`
- `查看当前状态` -> `get_status`
- `导出诊断报告` -> `export_diagnostics`
- `打开控制面板` -> `open_control_panel`
- `删除文件` -> denied / `not_allowed`
- `执行 powershell` -> denied / `not_allowed`
- `发微信消息` -> denied / `not_allowed`
- `操作浏览器` -> denied / `not_allowed`
- `今天天气怎么样` -> ordinary chat / `not_task`

Manual human validation passed:

- Control panel opens successfully.
- Safe capability commands work.
- Dangerous commands are rejected.
- Ordinary chat still routes normally.

PowerShell note:

- `Get-Content` may display Chinese source strings as garbled text because of console encoding.
- Python UTF-8 source reading is valid.
- Verified by checking:
  - `'打开日志' in service.py` -> True
  - `'鎵撳紑' in service.py` -> False

## Main Scripts

- `scripts/check_audio_devices.py`
- `scripts/record_test.py`
- `scripts/listen_once.py`
- `scripts/wake_loop.py`
- `scripts/voice_overlay.py`
- `scripts/settings_ui.py`
- `scripts/transcribe_test.py`
- `scripts/stt_server.py`
- `scripts/control_panel_web.py`

## Main Services

- `src/xiaohuang/audio_capture_service.py`
- `src/xiaohuang/vad_service.py`
- `src/xiaohuang/vad_recording_service.py`
- `src/xiaohuang/stt_service.py`
- `src/xiaohuang/stt_server_service.py`
- `src/xiaohuang/wake_word_service.py`
- `src/xiaohuang/wake_loop_service.py`
- `src/xiaohuang/overlay_state_service.py`
- `src/xiaohuang/reply_service.py`
- `src/xiaohuang/tts_service.py`
- `src/xiaohuang/audio_playback_service.py`
- `src/xiaohuang/llm_reply_service.py`
- `src/xiaohuang/reply_pipeline_service.py`
- `src/xiaohuang/config_service.py`
- `src/xiaohuang/logging_service.py`
- `src/xiaohuang/app_config_service.py`
- `src/xiaohuang/settings_config_file_service.py`
- `src/xiaohuang/status_control_service.py`
- `src/xiaohuang/control_panel_web_service.py`

## Main Capability Modules

Existing capabilities:

- `src/xiaohuang/capabilities/runtime_events/`
- `src/xiaohuang/capabilities/diagnostic_export/`
- `src/xiaohuang/capabilities/startup_diagnostics/`
- `src/xiaohuang/capabilities/preflight_check/`
- `src/xiaohuang/capabilities/local_commands/`

V1.4-A local command files:

- `src/xiaohuang/capabilities/local_commands/__init__.py`
- `src/xiaohuang/capabilities/local_commands/models.py`
- `src/xiaohuang/capabilities/local_commands/registry.py`
- `src/xiaohuang/capabilities/local_commands/service.py`

## Current Runtime Commands

Recommended environment setup before manual commands:

```powershell
cd E:\Projects\xiaohuang

$env:PYTHONPATH="E:\Projects\xiaohuang\src"
$env:PYTHONDONTWRITEBYTECODE="1"
$env:PYTHONUTF8="1"
$env:PYTHONIOENCODING="utf-8"
```

Open Web Control Panel:

```powershell
F:\for_xiaohuang\conda310\python.exe .\scripts\control_panel_web.py --debug
```

Open Web Control Panel with explicit config:

```powershell
F:\for_xiaohuang\conda310\python.exe .\scripts\control_panel_web.py --config "$env:USERPROFILE\.xiaohuang\config.json" --debug
```

Run STT server:

```powershell
F:\for_xiaohuang\conda310\python.exe .\scripts\stt_server.py --host 127.0.0.1 --port 8766
```

Run voice overlay:

```powershell
F:\for_xiaohuang\conda310\python.exe .\scripts\voice_overlay.py --debug
```

Run voice overlay with TTS:

```powershell
F:\for_xiaohuang\conda310\python.exe .\scripts\voice_overlay.py --debug --enable-tts
```

Run voice overlay with DeepSeek + TTS:

```powershell
$env:DEEPSEEK_API_KEY="your_key_here"
F:\for_xiaohuang\conda310\python.exe .\scripts\voice_overlay.py --debug --enable-llm --enable-tts
```

Common validation commands:

```powershell
F:\for_xiaohuang\conda310\python.exe -m compileall -q src scripts tests
F:\for_xiaohuang\conda310\python.exe -m unittest discover -s tests
F:\for_xiaohuang\conda310\python.exe .\scripts\voice_overlay.py --help
F:\for_xiaohuang\conda310\python.exe .\scripts\control_panel_web.py --help
F:\for_xiaohuang\conda310\python.exe .\scripts\stt_server.py --help
```

## Current Local Environment

Validated local runtime:

- Python: `F:\for_xiaohuang\conda310\python.exe`
- Project path: `E:\Projects\xiaohuang`
- STT server: `http://127.0.0.1:8766`
- microphone: device `0`
- ModelScope cache: `F:\for_xiaohuang\models\modelscope`
- HuggingFace cache: `F:\for_xiaohuang\models\huggingface`
- ffmpeg installed through `winget`

Recommended VAD command:

```powershell
F:\for_xiaohuang\conda310\python.exe scripts\listen_once.py --use-server --device 0 --vad --max-seconds 10 --silence-seconds 0.8 --countdown 3 --channels 1 --samplerate 16000
```

Recommended wake-loop command:

```powershell
F:\for_xiaohuang\conda310\python.exe scripts\wake_loop.py --device 0 --once --debug
```

Wake robustness test command:

```powershell
F:\for_xiaohuang\conda310\python.exe scripts\test_wake_text.py "小黄ang。"
```

Recommended wake phrase for manual testing:

- say `小黄小黄` for better STT stability

## Historical Notes

V1.1.3C Settings UI validation had passed earlier.

Former V1.1.3C details retained for history:

- Settings UI opened successfully.
- 6 tabs worked.
- Config saving worked.
- `--check` passed.
- saved config could start XiaoHuang.
- `贾维斯` wake phrase worked.
- `assistant.display_name` applied.
- LLM kept Jarvis identity.
- TTS played.
- session exit worked.
- logs showed no Traceback / ERROR / HTTPError / TypeError / UnboundLocalError.
- Detailed historical doc: `docs/V1.1.3C_SETTINGS_UI_VALIDATION.md`

V0.x / V1.x capability history:

- V0.3 validated device 0 recording -> WAV -> FunASR / SenseVoiceSmall Chinese transcription.
- V0.6 validated wake loop: say `小黄`, wait for wake detection, then speak command.
- V0.7 validated overlay repeated wake/result cycles.
- V0.9 added optional DeepSeek single-turn reply + rule fallback + optional edge-tts playback.
- V1.0.x extracted reply pipeline, added safe task router placeholder, and preserved rule/LLM/TTS behavior.
- V1.3 added PySide6 GPU STT direction, diagnostics, runtime events, open logs folder, startup failure diagnostics, and startup preflight check.
- V1.4-A added safe capability router MVP.

## Current Boundaries

Do not commit runtime artifacts:

- `data/recordings/*.wav`
- `data/recordings/wake/`
- `data/tts/`
- `logs/`
- `models/`
- `.venv/`
- `__pycache__/`
- `.claude/`
- `.env`
- `secrets.ps1`

Do not add in immediate next step:

- arbitrary command execution
- unrestricted PowerShell/cmd
- unrestricted file operations
- browser automation
- WeChat / QQ automation
- crawler/downloader
- OpenClaw-scale plugin system
- Docker sandbox
- multi-channel gateway
- remote nodes
- installer

## Recommended Next Step

Next recommended stage:

- V1.4-B Conversation Session Memory

Goal:

- Add short-term multi-turn conversation context.
- Keep it safe and local.
- Do not add more dangerous tools yet.
- Preserve existing single-turn behavior when session mode is off.
- Let follow-up commands use recent context naturally.

Example target behavior:

```text
User: 小黄，查看当前状态
XiaoHuang: 当前 STT 服务正常，控制面板正在运行。
User: 那运行启动前检查
XiaoHuang: 好，我现在运行启动前检查。
```

Suggested V1.4-B focus:

- conversation session store
- recent-turn memory
- session timeout
- max turns
- context summary for LLM/rule pipeline
- capability result history
- runtime event visibility
- tests for memory isolation and fallback behavior
