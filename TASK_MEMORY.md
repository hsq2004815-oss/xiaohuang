# Task Memory

## 当前最新状态

- **阶段**：V1.1.3C — Settings UI Prototype（开发完成，正在验证/收尾）
- **最新功能 commit**：`9f6b0ea` feat: add settings UI prototype
- **最新文档 commit**：`5883177` docs: record V1.1.3B verification results
- **新增**：`scripts/settings_ui.py` + `src/xiaohuang/settings_config_file_service.py`（V1.1.3C Settings UI）
- **分支**：`main...origin/main [ahead 1]`
- **工作区**：Settings UI `post_response_cooldown` 空值修复待提交；运行产物均 ignored
- **测试**：260 tests OK，compileall OK，settings_ui/voice_overlay help OK，settings_ui --check PASS

### V1.1.3C 验证收尾记录（2026-05-02）

- Settings UI 可打开，6 个 tab 齐全：Wake / Assistant / LLM / TTS / Conversation / Advanced。
- 人工保存 `assistant.display_name = 贾维斯测试` 后发现 blocker：Advanced 页 `post_response_cooldown=None` 被保存成字符串 `"None"`。
- 根因：Tkinter Entry 初始化时 `str(None)` 显示为 `"None"`，保存层未把 `"None"` / 空字符串规范成 JSON `null`。
- 修复：`scripts/settings_ui.py` 将 None 显示为空；`settings_config_file_service.normalize_ui_inputs()` 将 `overlay.post_response_cooldown` 的空值/`None`/`null` 规范为 `None`，数字字符串转 float。
- 已修复测试配置：`%USERPROFILE%\.xiaohuang\config_settings_ui_test.json` 中 `overlay.post_response_cooldown` 已恢复为 JSON `null`。
- 真实启动验证显示 `wake.phrases=贾维斯`、LLM persona、TTS、session exit 都生效；日志有 `source=llm`、`Session ended: reason=exit_phrase`，无 Traceback/ERROR/TypeError。
- 追加小修：浮窗内部状态文案不再硬编码“小黄”，会使用 `assistant.display_name` 和第一个 `wake.phrases`；默认仍保持“小黄”。
- 仍需用户真实启动验证：用 `config_settings_ui_test.json` 启动后说“贾维斯”，确认显示名/身份/TTS/session/logs。

### V1.1.3B 真实验证结果（2026-05-02）

| 验证项 | 结果 | 证据 |
|--------|------|------|
| Provider Router 链路 | ✅ | `Overlay reply: 我是贾维斯，你的桌面语音助手。 (source=llm)` |
| llm_ms 延迟追踪 | ✅ | latency summary 含 llm_ms |
| TTS 合成 + 播放 | ✅ | tts_synthesis_ms + tts_playback_ms 出现 |
| llm.enabled=false 边界 | ✅ | source=rule |
| missing key fallback | ✅ | source=rule_fallback_no_key，不崩溃，不泄露 key |
| Session 正常结束 | ✅ | Session ended: reason=exit_phrase |
| 无异常 | ✅ | 无 Traceback/ERROR/HTTPError/TypeError/UnboundLocalError |
| 贾维斯 identity | ✅ | 问"你是谁" → 自称"贾维斯"（非"小黄"） |

其他 provider（qwen/doubao/openai_compatible）已通过 11 个单元测试覆盖，真实 API 验证待用户配置对应 key。

### V1.1.3A 已完成

- 用户配置中控层 `app_config_service.py`（`XiaoHuangConfig` dataclass，8 个配置段）
- `--config` / `-ConfigPath` 打通
- `wake.phrases` 自定义唤醒词（完全替换默认值）
- `tts.voice` 配置
- `conversation` 参数配置
- `assistant.name` / `display_name` / `persona` 配置（V1.1.3A.4）
- `wake.phrases` 与 `assistant.name` 独立
- `llm` provider/model/base_url/api_key_env 预留
- `config.json` 不存 API key，只存 `api_key_env`
- `secrets.ps1` 仍加载
- PowerShell 不再用默认值覆盖 config
- 配置优先级：CLI > config.json > 默认值

### V1.1.3A 文档

- `docs/configuration.md` — 用户配置字段参考
- `docs/V1.1.3A_CONFIG_AUDIT.md` — 中控层收口审计

## 已踩坑（V1.1.3A 修复记录）

| # | 现象 | 根因 | 修复 commit |
|---|------|------|------------|
| 1 | `TypeError: 'XiaoHuangConfig' object is not subscriptable` | 新旧 `load_config` 同名覆盖；dataclass 被当作 dict 访问 | `af77b75` |
| 2 | `store_true` 的 `False` 覆盖 config 的 `true` | argparse `action="store_true"` 默认 `False`，直接赋值覆盖 | `cdeb5e5`（内建 `_or_config`） |
| 3 | `UnboundLocalError: local variable 'debug' referenced before assignment` | `debug = app_config.runtime.debug` 在 `apply_cli_overrides` 之前执行 | `cd1e218` |
| 4 | PowerShell 默认 `$Device = 0` 覆盖 `config.json` 的 `audio.device_id` | PS 参数默认值始终传入 Python | `763e566` + `50a3823` |
| 5 | argparse `--wake-phrases default="小黄,小黄小黄"` 覆盖 config | argparse 的 `default` 在未传参时生效 | `7beee12` |
| 6 | 唤唤醒"贾维斯"后助手自称"小黄" | `build_deepseek_request` 硬编码 system prompt | `67583d8` |

## 下一阶段建议

| 版本 | 内容 |
|------|------|
| V1.1.3B | LLM Provider Router ✅ 已完成 |
| V1.1.3C | Settings UI Prototype ✅ 开发完成，待人工 UI 验证 |
| V1.1.4 | HUD / 托盘 / 高级悬浮窗 |
| V1.2 | Wake Engine Abstraction |

---

## 历史阶段

<details>
<summary>V0.9.1 — DeepSeek 单句对话原型（收尾稳定版）</summary>

- Purpose: XiaoHuang V0.9.1 is a stabilization patch over V0.9 — DeepSeek error handling, LLM reply cleaning, TTS/LLM combination stability, artifact protection, and docs.
- V0.9.1 scope: no new features, no backend foundation, no multi-turn memory, no tool execution.
- V0.9.1 changes:
  - LLM reply execution claim filter (blocks "我已经打开"/"已下载"/"已执行" etc.)
  - Expanded tool request keywords (17 categories)
  - Overlay result displays fallback source note when DeepSeek unavailable
  - Improved shutdown: exception handler checks stop_event before sleeping
  - No-key startup message only in debug mode, not every round
  - API key never logged or included in reply text
  - Reply source tracked and displayed: llm/rule/rule_fallback_no_key/rule_fallback_error/tool_unavailable
- Key files: `scripts/voice_overlay.py`, `scripts/wake_loop.py`, `scripts/test_wake_text.py`, `src/xiaohuang/llm_reply_service.py`, `src/xiaohuang/reply_service.py`, `src/xiaohuang/tts_service.py`, `src/xiaohuang/wake_word_service.py`, `src/xiaohuang/wake_loop_service.py`.
- Current environment: use `F:\for_xiaohuang\conda310\python.exe`; recording works with `device 0`; ModelScope cache is `F:\for_xiaohuang\models\modelscope`; ffmpeg is installed through `winget` and available on PATH.
- Startup/test: dot-source `.\scripts\run_env.ps1`; set `PYTHONPATH=E:\Projects\xiaohuang\src`; run `& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests`.
- Last completed: V0.9.1 stabilization — 81 tests pass (9 new), compileall clean, --help verified.
- Overlay command: `& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug`.
- API key boundary: never commit or write `DEEPSEEK_API_KEY`; use environment variables only.
- Wake trap: V0.9.1 wake is short-recording + STT text matching, not openWakeWord/FunASR KWS.
- Still unfinished at V0.9.1: real KWS model, multi-turn dialogue, system tray, installer, desktop-assistant integrations.

</details>

<details>
<summary>V1.1.x 演进</summary>

| 版本 | Commits | 内容 |
|------|---------|------|
| V1.1.1D/E | `4cfb9a1`~`5db0e11` | command STT mode, session exit import, empty speech handling, TTS background playback |
| V1.1.2A/B/C | `652c00d`~`3b9f683` | latency metrics, adaptive follow-up session, session UI state fixes, session logs |
| V1.1.3A | `cdeb5e5`~`67583d8` | user config foundation, PowerShell respect config, dataclass/CLI/wake bug fixes, assistant identity |

</details>

## 运行环境（不变）

- Python: `F:\for_xiaohuang\conda310\python.exe`
- 麦克风: `device 0`
- 模型缓存: `F:\for_xiaohuang\models\modelscope`
- STT: FunASR / SenseVoiceSmall
- Git ignore: `data/recordings/*.wav`, `data/recordings/wake/`, `data/tts/`, `logs/`, `models/`, `.venv/`, `__pycache__/`
