# Task Memory

## 当前最新状态

- **阶段**：V1.1.4C — 托盘 PowerShell 调用 blocker 修复
- **最新功能 commit**：待提交 `feat: add tray launch controls`
- **最新文档 commit**：`65927ea` docs: record V1.1.4B tray validation
- **新增**：`scripts/settings_ui.py` + `src/xiaohuang/settings_config_file_service.py`（V1.1.3C Settings UI）
- **分支**：`main...origin/main`（V1.1.4C 开发前）
- **工作区**：V1.1.4C tray launch controls PowerShell argv 修复；运行产物均 ignored
- **测试**：279 tests OK、compileall OK、tray/settings/overlay help OK；命令构造确认优先 `pwsh.exe` + `-File` argv；真人托盘菜单点击需用户本机确认

### V1.1.3C 验证收尾记录（2026-05-02）

- Settings UI 可打开，6 个 tab 齐全：Wake / Assistant / LLM / TTS / Conversation / Advanced。
- 人工保存 `assistant.display_name = 贾维斯测试` 后发现 blocker：Advanced 页 `post_response_cooldown=None` 被保存成字符串 `"None"`。
- 根因：Tkinter Entry 初始化时 `str(None)` 显示为 `"None"`，保存层未把 `"None"` / 空字符串规范成 JSON `null`。
- 修复：`scripts/settings_ui.py` 将 None 显示为空；`settings_config_file_service.normalize_ui_inputs()` 将 `overlay.post_response_cooldown` 的空值/`None`/`null` 规范为 `None`，数字字符串转 float。
- 已修复测试配置：`%USERPROFILE%\.xiaohuang\config_settings_ui_test.json` 中 `overlay.post_response_cooldown` 已恢复为 JSON `null`。
- 真实启动验证显示 `wake.phrases=贾维斯`、LLM persona、TTS、session exit 都生效；日志有 `source=llm`、`Session ended: reason=exit_phrase`，无 Traceback/ERROR/TypeError。
- 追加小修：浮窗内部状态文案不再硬编码“小黄”，会使用 `assistant.display_name` 和第一个 `wake.phrases`；默认仍保持“小黄”。
- 最终真人验证已通过：Settings UI 保存后的 `config_settings_ui_test.json` 可真实启动小黄；“贾维斯”可唤醒，`assistant.display_name` 生效，问“你是谁”保持贾维斯身份，TTS 有声音，session exit 正常。
- 日志检查无 Traceback / ERROR / HTTPError / TypeError / UnboundLocalError。
- 详细记录见 `docs/V1.1.3C_SETTINGS_UI_VALIDATION.md`。

### V1.1.4A 设计记录（2026-05-02）

- 目标：让小黄从手动命令启动演进为可由托盘管理的桌面常驻助手。
- 本阶段只设计，不写托盘代码，不改 `.py/.ps1/.json/.yaml` 运行文件。
- 设计覆盖：启动/停止/重启小黄、打开 Settings UI、打开 logs 目录、状态显示、安全退出、进程识别、配置路径、日志、风险和验收。
- 推荐入口：未来新增 `scripts/tray_app.py`；可选服务 `process_status_service.py` / `launch_control_service.py`。
- 详细设计见 `docs/V1.1.4_TRAY_LAUNCH_CONTROL_DESIGN.md`。

### V1.1.4B 实现记录（2026-05-02）

- 新增 `scripts/tray_app.py`，使用 pystray + Pillow 创建最小托盘入口。
- 菜单只包含：打开设置、打开日志目录、关于/状态、退出托盘。
- `打开设置` 调用当前 Python 运行 `scripts/settings_ui.py --config <config_path>`，不阻塞托盘主线程。
- `打开日志目录` 创建并打开 `logs/`。
- `退出托盘` 只停止托盘图标，不调用 `stop_xiaohuang.ps1`，不停止 STT/overlay。
- 新增依赖：`pystray>=0.19.5`、`Pillow>=10.0`。
- 自动验证：267 tests OK、compileall OK、tray/settings/overlay help OK。
- 启动 smoke：`tray_app.py --config config_settings_ui_test.json` 可启动为常驻进程。
- 最终真人验证已通过：托盘图标出现、右键菜单打开、打开 Settings UI、读取 `config_settings_ui_test.json`、打开 `logs/`、关于/状态、退出托盘均正常。
- 边界验证通过：V1.1.4B 没有启动/停止/重启小黄；退出托盘不会停止 STT server / voice_overlay；未影响 voice_overlay / wake / session / TTS / LLM router 主链路。
- 详细记录见 `docs/V1.1.4B_TRAY_VALIDATION.md`。

### V1.1.4C 实现记录（2026-05-02）

- 新增 `src/xiaohuang/launch_control_service.py`，封装 PowerShell 启停命令构造、重启顺序、日志目录、进程检测和状态摘要。
- `scripts/tray_app.py` 菜单新增：启动小黄、停止小黄、重启小黄。
- 启动小黄会先检测 STT server / voice_overlay；只有二者都存在才提示“已在运行”，避免重复启动。
- 启动命令会传递当前托盘 `--config` 到 `start_xiaohuang.ps1 -ConfigPath <config_path>`，避免丢失 `config_settings_ui_test.json`。
- 停止命令调用 `stop_xiaohuang.ps1 -StopSttServer`；退出托盘仍只退出托盘程序，不停止小黄。
- 本阶段未修改 PowerShell、voice_overlay、wake、session、TTS、LLM router，也未新增依赖。
- 自动验证：274 tests OK、compileall OK、tray_app/settings_ui/voice_overlay help OK；托盘进程受控启动 5 秒 smoke 后按 PID 停止，未触发小黄启动/停止菜单。
- Blocker 修复：用户发现托盘启动后只有 `voice_overlay.py`、没有 `stt_server.py`，`/health` 连接拒绝；根因是启动防重复逻辑用 `any_running`，overlay-only partial 状态被误判为已运行并跳过完整启动。
- 修复策略：新增 `ProcessStatus.is_fully_running` / `is_partial` 和 `build_start_sequence_for_status()`；partial/broken 状态下“启动小黄”先调用 `stop_xiaohuang.ps1 -StopSttServer` 清理，再调用 `start_xiaohuang.ps1 -ConfigPath <config_path>` 完整拉起链路。
- PowerShell 调用 blocker：`powershell.exe -File start_xiaohuang.ps1` 会在 dot-source `run_env.ps1` 时解析示例命令里的 `&` / 引号失败；同一 argv list 用 `pwsh.exe` 可正常拉起 STT server 和 overlay。
- 修复策略：启停命令仍返回 argv list、仍用 `-File`、仍 `shell=False`，但优先解析 `pwsh.exe`，找不到才回退 `powershell.exe`；不修改 `start_xiaohuang.ps1` / `stop_xiaohuang.ps1` / `run_env.ps1`。

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
| V1.1.3C | Settings UI Prototype ✅ 最终真人验证通过，阶段性收口 |
| V1.1.4B | 最小托盘入口 ✅ 已实现并真人验证通过 |
| V1.1.4C | 托盘启动 / 停止 / 重启控制，自动验证后需真人验证 |
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
