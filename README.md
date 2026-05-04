# 小黄 Windows 桌面 AI 助手 V1.2E（openWakeWord overlay listener）

小黄是一个 Windows 桌面 AI 助手项目。当前已从 V0.9.1 单句原型演进到 V1.2E openWakeWord feature flag 接入阶段。

管道：唤醒后听一句话 → STT server 转写 → DeepSeek 单句回复（或规则 fallback） → 可选 edge-tts 播放 → 多轮会话（可选）。

```text
config.json / secrets.ps1 → STT server 常驻 → voice_overlay 悬浮窗 → STT 文本匹配唤醒词 → VAD 录命令句 → STT server 转写 → DeepSeek 单句回复或规则 fallback → 可选 edge-tts 播放 → 多轮会话 follow-up
```

## 当前能力

### 交互模式

- **resident-hidden**：启动时隐藏悬浮窗，唤醒后弹出
- **conversation-session**：唤醒后保持多轮对话，无需反复唤醒
- **adaptive follow-up**：每轮回复后自动进入追问窗口，超时或无语音自动退出
- **no_speech / empty speech 处理**：静音重试、空转写跳过，超次数退出会话
- **session end reason logs**：会话结束原因记录（no_speech / max_turns / timeout / exit_phrase）

### 语音与回复

- STT 引擎：FunASR SenseVoiceSmall，常驻 server 模式
- LLM 回复：DeepSeek 单句回复 + 本地规则 fallback
- TTS 后台播放：edge-tts 合成 → 后台音频播放，不阻塞 UI
- latency metrics：每轮录音/STT/LLM/TTS 耗时追踪
- 回复来源追踪：llm / rule / rule_fallback_no_key / rule_fallback_error / tool_unavailable

### 用户配置中控层（V1.1.3A 核心）

- **config.json**：统一配置入口，默认路径 `%USERPROFILE%\.xiaohuang\config.json`
- **--config / -ConfigPath**：CLI 和 PowerShell 指定配置文件路径
- **wake.phrases**：自定义唤醒词（如 `["贾维斯"]`），完全替换默认值，不合并
- **wake.aliases**：低置信度唤醒别名
- **audio.device_id**：麦克风设备 ID，可通过 config 或 `--device` 覆盖
- **tts.voice**：edge-tts 语音名
- **conversation 参数**：followup_timeout / max_turns / max_session_seconds / max_no_speech_retries
- **assistant.name / display_name / persona**：助手身份名、悬浮窗标题、LLM 系统提示词
- **wake.phrases 与 assistant.name 独立**：唤醒词和助手身份是两个独立配置段，可分别设置
- **llm provider/model/base_url/api_key_env**：已预留，当前 deepseek 实际接入
- **API key 不入 config**：config.json 只存 `api_key_env` 环境变量名，真实 key 走 `secrets.ps1` 或环境变量
- **PowerShell 不覆盖 config**：只有显式传参才生效，未传参时 config 值优先

### 配置优先级

```
显式 CLI / PowerShell 参数  >  config.json  >  内置默认值
```

### 启动方式

```powershell
# 一键启动（STT server + overlay）
.\scripts\start_xiaohuang.ps1 -ConfigPath "$env:USERPROFILE\.xiaohuang\config.json"

# 使用测试配置
.\scripts\start_xiaohuang.ps1 -ConfigPath "$env:USERPROFILE\.xiaohuang\config_test.json"

# 停止
.\scripts\stop_xiaohuang.ps1 -StopSttServer
```

## 当前边界

- **还不执行工具**：LLM 回复不接浏览器/QQ/微信/opencode/opencli/爬虫/文件系统
- **还不做复杂 Settings UI**：配置通过文本编辑 `config.json`
- **还不做高级 HUD / 安装器**：当前已有 V1.1.4C 托盘启动控制，但不做开机自启或安装器
- **当前 wake 仍是 STT 文本匹配**：不是真正 KWS 模型（openWakeWord / fsmn-kws）
- **LLM 仍是单句回复**：不做多轮上下文记忆
- **不做离线 TTS**：edge-tts 依赖网络

## 环境

### 本机已验证环境

- Python: `F:\for_xiaohuang\conda310\python.exe`
- 麦克风：`device 0`
- 模型缓存：`F:\for_xiaohuang\models\modelscope`
- STT：FunASR / SenseVoiceSmall
- ffmpeg：已通过 `winget` 安装

### 启动前准备

```powershell
cd E:\Projects\xiaohuang
. .\scripts\run_env.ps1
```

### API Key 配置

```powershell
# 推荐：创建 secrets.ps1（不会提交到 Git）
notepad "$env:USERPROFILE\.xiaohuang\secrets.ps1"
# 内容：$env:DEEPSEEK_API_KEY = "sk-..."

# 或每次启动时设置
$env:DEEPSEEK_API_KEY = "sk-..."
```

### STT 安装

```powershell
python -m pip install funasr modelscope torch torchaudio
```

---

## 历史阶段 / 已完成演进

<details>
<summary>V0.9.1 — DeepSeek 单句对话原型（收尾稳定版）</summary>

V0.9.1 对 V0.9 的 DeepSeek 单句回复做了错误处理、回复清洗和稳定性收尾。

### V0.9.1 收尾内容

- LLM 回复执行声明过滤（拦截"我已经打开"/"已下载"/"已执行"等）
- 扩展工具请求关键词（17 类）
- 浮窗 fallback 时显示来源提示
- 异常处理检查 stop_event，避免关闭后继续 sleep
- 无 key 启动提示只在 debug 模式出现
- API key 不入日志、不入回复文本
- 回复来源追踪：llm/rule/rule_fallback_no_key/rule_fallback_error/tool_unavailable
- TTS 失败不影响文本显示；播放失败只 warning，不崩溃
- 关闭浮窗或 Esc 后，后台线程停止

### V0.9 原始能力

- 枚举 Windows 麦克风
- 录制固定时长 WAV 到 `data/recordings/`
- 能量阈值 VAD 自动截断
- FunASR SenseVoiceSmall 转写
- 脚本日志输出到 `logs/`
- `wake_loop.py` 控制台唤醒原型（STT 文本匹配）
- `voice_overlay.py` Tkinter 360x120 置顶悬浮窗 + Canvas 音波动画
- `--enable-llm` DeepSeek 单句回复
- `--enable-tts` edge-tts 语音合成播放
- 回复后冷却期避免 TTS 尾音进入 wake check
- STT server `/transcribe` 路径安全边界
- wake scoring 尾音和低风险 alias 处理
- 唤醒短音频默认删除（`--keep-wake-recordings` 可保留）

### V0.9.1 界限

- 单句回复，不保存对话历史
- 不执行工具
- 不接 openWakeWord / FunASR KWS 真实模型
- 不做多轮对话记忆
- 不做安装器；V1.1.4C 托盘提供启动/停止/重启、打开设置、打开日志目录和退出托盘

</details>

<details>
<summary>V1.1.x 演进路径</summary>

| 版本 | 内容 |
|------|------|
| V1.1.1 | 修复 TTS 后台播放、空语音处理、会话退出导入、command STT 模式 |
| V1.1.2 | latency metrics、adaptive follow-up session window、会话 UI 状态修复、会话日志 |
| V1.1.3A | 用户配置中控层：config.json、app_config_service、wake/audio/llm/tts/conversation/overlay/runtime/assistant 配置段、assistant identity |
| V1.1.3B | LLM Provider Router：deepseek/qwen/doubao/openai_compatible 多 provider 切换 |
| V1.1.3C | Settings UI Prototype：Tkinter 配置编辑器（settings_ui.py） |
| V1.1.4 | Resident / Tray / Launch Control：V1.1.4C 托盘启动/停止/重启控制已实现，等待真人验证 |

</details>

## 版本控制

不要提交：

- `data/recordings/*.wav`
- `data/recordings/wake/`
- `data/tts/`
- `logs/`
- `models/`
- `.venv/`
- `__pycache__/`

## 文档

- [configuration.md](docs/configuration.md) — 用户配置字段参考
- [LLM_PROVIDER_CONFIGURATION.md](docs/LLM_PROVIDER_CONFIGURATION.md) — LLM Provider 多 provider 配置指南
- [V1.1.3A_CONFIG_AUDIT.md](docs/V1.1.3A_CONFIG_AUDIT.md) — 中控层收口审计
- [V1.1.3C_SETTINGS_UI_VALIDATION.md](docs/V1.1.3C_SETTINGS_UI_VALIDATION.md) — Settings UI 最终真人验证记录
- [V1.1.4_TRAY_LAUNCH_CONTROL_DESIGN.md](docs/V1.1.4_TRAY_LAUNCH_CONTROL_DESIGN.md) — 托盘常驻与启动控制设计
- [V1.1.4B_TRAY_VALIDATION.md](docs/V1.1.4B_TRAY_VALIDATION.md) — 最小托盘程序真人验证记录
- [V1.1.4D_STATUS_CONTROL_PANEL_DESIGN.md](docs/V1.1.4D_STATUS_CONTROL_PANEL_DESIGN.md) — 基础状态 UI / 控制面板设计
- [V1.2_WAKE_ENGINE_DESIGN.md](docs/V1.2_WAKE_ENGINE_DESIGN.md) — Wake Engine / 专用唤醒增强设计
- [V1.2B_OPENWAKEWORD_DEMO_VALIDATION.md](docs/V1.2B_OPENWAKEWORD_DEMO_VALIDATION.md) — openWakeWord 独立 demo 验证记录
- [V1.2C_WAKE_ENGINE_SERVICE_DESIGN.md](docs/V1.2C_WAKE_ENGINE_SERVICE_DESIGN.md) — WakeEngine service 抽象层设计
- [V1.2D_OPENWAKEWORD_ADAPTER_VALIDATION.md](docs/V1.2D_OPENWAKEWORD_ADAPTER_VALIDATION.md) — OpenWakeWordAdapter 接入前安全验证记录
- [V1.2D_B_WAKE_ENGINE_SAFETY_VALIDATION.md](docs/V1.2D_B_WAKE_ENGINE_SAFETY_VALIDATION.md) — Wake Engine 麦克风生命周期安全验证记录
- [V1.2D_C_WAKE_COMMAND_BRIDGE_VALIDATION.md](docs/V1.2D_C_WAKE_COMMAND_BRIDGE_VALIDATION.md) — WakeEvent 到命令录音入口的模拟桥接验证记录

## Settings UI

```powershell
# 打开设置界面
& "F:\for_xiaohuang\conda310\python.exe" scripts\settings_ui.py

# 指定配置文件
& "F:\for_xiaohuang\conda310\python.exe" scripts\settings_ui.py --config "path\to\config.json"

# 只校验不打开窗口
& "F:\for_xiaohuang\conda310\python.exe" scripts\settings_ui.py --check
```

## Tray App

V1.1.4C 托盘入口支持启动小黄、停止小黄、重启小黄、打开设置、打开日志目录、关于/状态和退出托盘。

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\tray_app.py --config "$env:USERPROFILE\.xiaohuang\config.json"
```

V1.1.4C 边界：

- “启动小黄”调用 `scripts/start_xiaohuang.ps1 -ConfigPath <config_path>`。
- “停止小黄”调用 `scripts/stop_xiaohuang.ps1 -StopSttServer`。
- “重启小黄”先停止再启动。
- “已在运行”必须同时检测到 STT server 和 `voice_overlay.py`；如果只检测到其中一个，托盘会先清理残留再完整启动。
- 托盘调用 PowerShell 使用 argv list + `-File` + `shell=False`，优先 `pwsh.exe`，找不到再回退 `powershell.exe`。
- 启动/重启会等待 readiness：STT server 进程、`voice_overlay.py` 进程和 `/health` ready/model_loaded 都满足后才提示已就绪。
- 启动/停止/重启带操作锁；进行中重复点击会提示“正在执行操作，请稍候”，不会并发启动多套脚本。
- 启动命令异步发出，readiness 成功后释放操作锁；`logs/tray_app.log` 会记录 operation acquired/release。
- “退出托盘”只退出托盘程序，不停止 STT server 或 `voice_overlay.py`。
- 托盘程序不读取、不显示、不保存真实 API key。

## V1.1.4D Status Control Panel

V1.1.4D-A 已新增最小可用 Tkinter 控制面板，用于显示 STT server readiness、`voice_overlay.py` 运行状态、health/model_loaded、当前 config 摘要和“是否可以说贾维斯”。控制面板复用 `launch_control_service.py` 和 `status_control_service.py`，不修改 `voice_overlay.py` 主链路，不新增 PySide6/Qt/WebView 等重依赖。

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\control_panel.py --config "$env:USERPROFILE\.xiaohuang\config_settings_ui_test.json"
```

托盘菜单已新增“打开控制面板”。关闭控制面板不会停止小黄。

V1.1.4D-A readiness 修复：控制面板和启动/重启等待现在统一复用 `launch_control_service.detect_xiaohuang_processes()` 的命令行分类；`voice_overlay.py` / `stt_server.py` 支持绝对路径、相对 `scripts\...`、正斜杠路径、带引号路径和 `pythonw.exe` 启动形式。启动/重启等待超时后会再读取一次控制面板状态，若最终已 `READY` / `can_wake_now=True`，不再返回 `timeout_voice_overlay_missing` 的未就绪弹窗。

V1.1.4D-B 流畅性修复：控制面板周期刷新和手动刷新不再在 Tkinter 主线程直接执行进程检测、PowerShell `Get-CimInstance` 或 STT `/health` 网络请求；刷新由后台线程采集状态，再通过 `root.after(0, ...)` 回到主线程渲染。刷新带 `refresh_in_progress` / `pending_refresh` / `refresh_generation`，避免检测线程堆叠，也避免旧刷新结果覆盖较新的 READY 状态。启动/停止/重启仍在后台线程执行，操作结束后由同一 worker 采集最终状态，READY 时不会弹出陈旧的 `timeout_voice_overlay_missing`。

V1.1.4D-B 竞态修复：启动/重启操作完成时，操作 worker 会在后台线程内用短暂 grace window 采集 `final_status`，主线程只用该 operation completion result 决定弹窗；若 `final_status` 已 READY / `can_wake_now=True`，清空最近错误并按成功提示。operation completion pending 期间普通周期刷新不会交叉覆盖操作结果。

V1.1.4B 真人验证结果：托盘图标、右键菜单、打开 Settings UI、读取 `config_settings_ui_test.json`、打开 `logs/`、关于/状态、退出托盘均正常。退出托盘不会停止 STT server 或 `voice_overlay.py`，也未影响 wake / session / TTS / LLM router 主链路。

## V1.2 Wake Engine Design

V1.2A 已新增 docs-only 设计，用于规划从当前 STT 文本匹配唤醒演进到专用 Wake Word / KWS 引擎。推荐路线是先以 openWakeWord 做独立 demo 和 adapter 抽象，保留当前 STT 文本匹配作为 fallback；Porcupine 作为体验标杆/可选方案，wyoming-openwakeword 作为 server 架构参考，sherpa-onnx / FunASR KWS 作为中长期对比研究。V1.2A 不修改 `voice_overlay.py`、控制面板、托盘、PowerShell 或运行配置。

V1.2B 已新增独立 demo harness：`scripts/wake_engine_demo.py`。该脚本支持 `--help`、`--check-install`、`--dry-run` 和 `--list-devices`，未安装 openWakeWord 时会输出清晰的 optional dependency 状态并保持自动验证可继续。

V1.2B-1 已增加 demo 层 wake event cooldown 合并：默认 `--cooldown-seconds 2.5`，同一 label 在 cooldown 内的连续 raw detections 只统计为一次 `coalesced_events`。真人验证结果：`openwakeword 0.6.0` / `onnxruntime 1.23.2` / `sounddevice 0.5.5` 可用，device 0 可监听，英文 `hey_jarvis` 可稳定触发，静默测试 `frames=748, detections=0`；当前仍不是中文“贾维斯”模型，暂不接入 `voice_overlay.py`。

V1.2C 已新增 `src/xiaohuang/wake_engine_service.py`，把 `WakeEvent`、`WakeEngineStatus`、`WakeEventCoalescer`、`WakeEventStats` 和 `FakeWakeEngine` 沉淀为正式服务层。`scripts/wake_engine_demo.py` 已复用服务层 coalescer，保持 `--help` / `--check-install` / `--dry-run` / 实时 demo 行为不变。

V1.2D-A 已新增 `src/xiaohuang/openwakeword_adapter.py`，把 openWakeWord optional imports、dependency check、model/runtime lifecycle、sounddevice frame loop、`WakeEvent` callback 和 per-label cooldown 统计封装到 adapter harness。`scripts/wake_engine_demo.py` 的真实监听路径已改为走 `OpenWakeWordAdapter.run_for_duration()`；`--help` / `--dry-run` 仍不加载模型、不打开麦克风，`--check-install` 只做结构化依赖检查。本阶段仍不修改 `voice_overlay.py`，不替换 STT 文本唤醒，不训练中文“贾维斯”模型，不新增依赖；后续 D-B/D-C 已继续验证麦克风释放和 wake -> fake command starter 桥接。

V1.2D-B 已在 `scripts/wake_engine_demo.py` 新增 `--safety-check`，支持 `--repeat` 和 `--gap-seconds`，用于重复验证 adapter start/run/stop、异常释放、`KeyboardInterrupt` 释放和 `status_after_stop.running=false`。本阶段仍不接入 `voice_overlay.py`，不替换 STT 文本唤醒，不训练中文“贾维斯”模型；真实 command recorder、TTS pause/cooldown 和 `stt_text` fallback 仍需在正式接入前单独验证。

V1.2D-B 真人 safety-check 已通过：device 0、10 秒、2 轮重复运行后 `all_rounds_completed=true`、`microphone_released=true`、`errors=0`；第 2 轮 `frames=123`、`raw_detections=17`、`coalesced_events=3`、`suppressed_detections=14`、`status_after_stop running=false ready=false model_loaded=true error=-`。后续 V1.2D-C 已完成 wake event -> command recorder 模拟桥接设计/验证，仍不直接改正式 `voice_overlay.py` 主链路。

V1.2D-C 已新增 `src/xiaohuang/wake_command_bridge_service.py` 和 `scripts/wake_command_bridge_demo.py`，用 fake `WakeEvent` 与 fake command starter 验证 bridge 状态机：`accepted`、`cooldown`、`command_active`、`tts_active`、`disabled`、`bridge_busy`、`invalid_event`、`recorder_error`。默认 demo 不打开麦克风、不启动 openWakeWord/STT/overlay/LLM/TTS；`events=3`、`interval=0.5`、`cooldown=2.5` 时只会启动一次 fake command starter。本阶段仍不修改 `voice_overlay.py`，不替换 STT 文本唤醒；下一步是 V1.2D-D 只读分析正式 command recorder 接入点。

V1.2E 已把 openWakeWord 以 feature flag 接入 `voice_overlay.py` 主链路。默认 `wake.engine` 仍是 `stt_text`，旧 STT 文本唤醒行为不变；只有显式配置 `wake.engine="openwakeword"` 时才启动 `OpenWakeWordAdapter`。openWakeWord 由 `voice_overlay.py` 自己启动后台 listener thread，收到 accepted `WakeEvent` 后投递到 overlay worker，并进入旧 VAD command recorder / STT command 入口。openWakeWord 依赖或运行失败时，`fallback_enabled=true` 会回退到旧 `stt_text` 路径；`fallback_enabled=false` 会记录错误并安全停止。

V1.2E listener 日志关键字：启动时输出 `wake_engine_selected`、`wake_fallback_enabled`、`wake_device_index`、`wake_cooldown_seconds`、`wake_sensitivity`；openWakeWord 分支输出 `openwakeword_listener_starting`、`openwakeword_listener_running`、`openwakeword_listener_cycle_done`；accepted 事件输出 `openwakeword_wake_event`、`openwakeword_bridge_decision`、`command_record_start source=openwakeword`。command recording 和 TTS 播放期间会屏蔽/暂停 wake event，避免重复触发或自唤醒。

最小 openWakeWord 配置示例：

```json
{
  "wake": {
    "engine": "openwakeword",
    "phrases": ["贾维斯"],
    "fallback_enabled": true,
    "sensitivity": 0.5,
    "cooldown_seconds": 2.5,
    "device_index": 0,
    "model_path": null,
    "model_name": "hey_jarvis"
  }
}
```

人工验证建议：先用默认/`stt_text` 确认旧“贾维斯”唤醒仍可用；再切到 `openwakeword` 后说 “hey jarvis”，确认进入命令录音、命令结束后能继续等待下一次唤醒，TTS 播放期间不重复自唤醒；需要回滚时改回 `wake.engine="stt_text"`。
