# 小黄 Windows 桌面 AI 助手 V1.1.3A（用户配置中控层）

小黄是一个 Windows 桌面 AI 助手项目。当前已从 V0.9.1 单句原型演进到 V1.1.3A 可配置桌面语音助手阶段。

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
- **还不做 HUD / 托盘 / 安装器**：当前只有 Tkinter 悬浮窗
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
- 不做桌面托盘或安装器

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
| V1.1.4 | Resident / Tray / Launch Control：托盘常驻、启动/停止/重启、打开设置和日志目录（设计完成，待实现） |

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

V1.1.4B 提供最小托盘入口，只支持打开设置、打开日志目录和退出托盘。它不会启动、停止或重启小黄主链路；这些能力留到 V1.1.4C。

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\tray_app.py --config "$env:USERPROFILE\.xiaohuang\config.json"
```
