# 小黄 V0.9.1 DeepSeek 单句对话原型（收尾稳定版）

小黄是一个 Windows 桌面 AI 助手项目。当前 V0.9.1 对 V0.9 的 DeepSeek 单句回复做了错误处理、回复清洗和稳定性收尾，不新增功能。

管道：唤醒后听一句话 → STT server 转写 → DeepSeek 单句回复（或规则 fallback） → 可选 edge-tts 播放。

```text
STT server 常驻 -> voice_overlay 悬浮窗 -> STT 文本匹配“小黄” -> VAD 录命令句 -> STT server 转写 -> DeepSeek 单句回复或规则 fallback -> 可选 edge-tts 播放
```

## 当前范围

- V0.9 是 DeepSeek 单句回复原型，不是多轮对话，不执行工具
- V0.9.1 对 DeepSeek 错误处理、LLM 回复清洗和 TTS/LLM 组合稳定性做了收尾
- `--enable-llm` 只生成单句回复，不调用 OpenCLI / opencode / 浏览器 / QQ / 微信 / 爬虫
- API key 必须通过环境变量 `DEEPSEEK_API_KEY` 设置，不允许写入配置文件、README、日志或代码
- 未配置 key 或 DeepSeek 调用失败时，自动 fallback 到本地规则回复
- LLM 回复会经过清洗：去多余换行、去首尾空格、限制 30 汉字以内、过滤虚假执行声明
- 浮窗在 fallback 时显示简短状态提示（如 "DeepSeek 不可用，已使用本地回复"）
- 关闭浮窗或按 Esc 后，后台线程停止，不再继续刷 Wake check 输出
- TTS 失败不影响文本显示；播放失败只 warning，不崩溃
- 下一阶段建议是 V1.0 Backend Foundation，而不是直接接工具

- 枚举 Windows 当前可用麦克风
- 选择麦克风设备录制固定时长音频
- 保存 WAV 到 `data/recordings/`
- 默认仍支持固定 5 秒录音
- `listen_once.py --vad` 支持能量阈值版 VAD 自动截断
- 通过 FunASR SenseVoiceSmall 转写 WAV 文件
- 脚本日志输出到 `logs/`
- 录音前倒计时，默认 3 秒
- 录音参数可配置：`--channels`、`--samplerate`
- 录音后打印 peak amplitude 和 rms amplitude，并提示静音或削波风险
- 设备枚举输出推荐标记，帮助避开扬声器、输出设备或立体声混音
- 一键运行 `listen_once.py`，完成录音、转写和耗时诊断
- 耗时诊断包含 `record_seconds`、`transcribe_seconds`、`total_seconds`
- server 模式会额外显示 `server_model_init_seconds`，它表示 STT server 启动时的模型初始化耗时，不代表每次请求都会重新加载模型
- 本地 STT server 只监听 `127.0.0.1`，避免开放到外网
- `listen_once.py --use-server` 可复用常驻模型；server 不可用时默认直接报错
- 只有显式加 `--allow-local-fallback` 时，server 不可用才允许回退到本地直接 STT
- VAD 模式会显示 `actual_recording_seconds`、`stop_reason`、`speech_detected` 和 `energy_threshold`
- `wake_loop.py` 支持控制台版唤醒词原型，命中“小黄”或“小黄小黄”后自动进入 VAD 命令录音
- V0.7.2 对 STT 文本匹配唤醒做了 scoring 优化，支持 `小黄ang` 等尾音和低风险 alias
- `wake_loop.py` 默认要求 STT server 可用，不做本地 fallback
- `wake_loop.py` 默认删除等待唤醒阶段的短录音临时 WAV；只有 `--keep-wake-recordings` 才保留
- STT server 只接受项目 `data/recordings/` 下存在的 `.wav` 文件路径
- `voice_overlay.py` 提供 360x120 左右的 Tkinter 置顶小窗口，显示状态文案和简易 Canvas 音波动画
- `voice_overlay.py` 复用 `wake_loop_service.py`，不复制控制台 wake loop 核心流程
- `voice_overlay.py` 在命令转写后生成规则版单句回复，并显示 `你说：... / 小黄：...`
- `voice_overlay.py --enable-llm` 会在配置 `DEEPSEEK_API_KEY` 后调用 DeepSeek 单句回复
- DeepSeek 未启用、未配置 key 或调用失败时，自动回退到本地规则回复
- `voice_overlay.py --enable-tts` 会使用 edge-tts 生成 mp3 到 `data/tts/` 并尝试播放
- `--enable-tts` 默认关闭；不开启时只显示文字回复，不联网合成语音

## 明确不包含

- V0.9 是 DeepSeek 单句回复原型，不是多轮对话
- V0.9 不执行工具；`--enable-llm` 只生成回复，不接 OpenCLI / opencode / 浏览器 / QQ / 微信 / 爬虫
- 不训练真正的 openWakeWord 自定义模型
- 不接真正低功耗实时 KWS 模型
- 不做多轮对话记忆
- 不做复杂人格系统
- 不接 PersonaPlex / Moshi
- 不接 OpenCLI
- 不接 opencode
- 不接 QQ / 微信
- 不接爬虫
- 不做完整任务调度系统
- 不做桌面托盘或安装器

## 环境建议

优先使用项目虚拟环境或 conda 环境，不要安装到全局 Python。

### 本机已验证通过的运行环境

当前已在以下环境跑通：

- Python: `F:\for_xiaohuang\conda310\python.exe`
- 麦克风设备：`device 0`
- 模型缓存：`F:\for_xiaohuang\models\modelscope`
- STT：FunASR / SenseVoiceSmall
- ffmpeg：已通过 `winget` 安装，并且当前 PATH 可用

已验证成功链路：

```text
device 0 麦克风录音 -> 保存 WAV -> SenseVoiceSmall 中文转写 -> 控制台输出文本
```

成功转写示例：

```text
输入语音：小黄小黄帮我测试一下语音识别功能，我们正在开发语音识别助手。
输出文本：小黄小黄帮我测试一下语音识别功能，我们正在开发语音识别助手。
```

### 推荐运行命令

先用点执行加载 V0.9 本机运行环境，确保 `MODELSCOPE_CACHE` / `HF_HOME` 保留在当前 PowerShell 会话：

```powershell
cd E:\Projects\xiaohuang
. .\scripts\run_env.ps1
```

检查设备：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\check_audio_devices.py
```

当前实测推荐参数：

```text
--device 0
--vad
--max-seconds 10
--silence-seconds 0.8
--use-server
```

使用已验证的 `device 0` 录音 5 秒：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\record_test.py --device 0 --seconds 5 --countdown 3 --channels 1 --samplerate 16000
```

转写录音文件：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\transcribe_test.py <wav_path>
```

一键录音并自动转写：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\listen_once.py --device 0 --seconds 5 --countdown 3 --channels 1 --samplerate 16000
```

启动常驻 STT server：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\stt_server.py
```

启动完成后会显示：

```text
STT server ready
```

第一次启动 server 仍然会慢，因为需要加载 SenseVoiceSmall；后续请求会复用常驻模型，主要耗时应集中在实际转写。

通过 server 一键录音并转写：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\listen_once.py --use-server --device 0 --seconds 5 --countdown 3 --channels 1 --samplerate 16000
```

通过 server 一键录音、VAD 自动截断并转写：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\listen_once.py --use-server --device 0 --vad --max-seconds 10 --silence-seconds 0.8 --countdown 3 --channels 1 --samplerate 16000
```

控制台唤醒词原型，检测一次唤醒并转写一次命令后退出：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\wake_loop.py --device 0 --once --debug
```

不录音测试唤醒文本匹配：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\test_wake_text.py "小黄ang。"
```

音波悬浮窗原型：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug
```

单句回复 + TTS 原型：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug --enable-tts
```

DeepSeek 单句回复 + TTS 原型：

```powershell
$env:DEEPSEEK_API_KEY="你的 key"
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug --enable-llm --enable-tts
```

查看悬浮窗参数：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --help
```

V0.6 当前成功测试结果：

```text
STT server 常驻可用
wake_loop.py --device 0 --once --debug 可进入等待状态
说“小黄”后可检测唤醒并输出 Wake word detected.
唤醒后进入 Listening for command...
命令句“帮我测试一下唤醒后的命令识别。”可进入 STT server 转写流程并输出 Command transcription
```

V0.7 悬浮窗实测结果：

```text
voice_overlay.py --device 0 --debug 已连续完成多轮唤醒、VAD 命令录音、STT server 转写和悬浮窗结果显示。
Wake check transcription: 小黄。
Command transcription: 怎么说，这一波。
Wake check transcription: 小黄。
Command transcription: 嗯，还不错。
Wake check transcription: 哦。
Wake check transcription: 小黄。
Command transcription: 你有什么感觉吗？
Wake check transcription: 小黄。
Command transcription: 你想干嘛？
Wake check transcription: 小黄。
Command transcription: 我很生气。
```

其中 `哦。` 没有命中唤醒词，流程继续等待下一轮 `小黄`，说明普通调试输出不会把非唤醒短句误当成命令入口。

转写已有 WAV：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\stt_client.py data\recordings\test_时间戳.wav
```

### venv

```powershell
cd E:\Projects\xiaohuang
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### conda

```powershell
conda create -n xiaohuang python=3.10
conda activate xiaohuang
cd E:\Projects\xiaohuang
python -m pip install -r requirements.txt
```

## STT 安装说明

`transcribe_test.py` 使用 FunASR SenseVoiceSmall。基础依赖不会默认安装完整 STT 栈，因为 FunASR、PyTorch、torchaudio 和模型下载在 Windows 上可能需要按机器环境处理。

在项目环境中安装：

```powershell
python -m pip install funasr modelscope torch torchaudio
```

如果 Windows 依赖解析失败，先只验证录音链路；再考虑使用 FunASR 官方 Windows SDK 或 ONNX 导出方案。

## 运行步骤

建议每次运行 V0.9 脚本前先点执行：

```powershell
cd E:\Projects\xiaohuang
. .\scripts\run_env.ps1
```

该脚本只会切换到项目目录、设置 `PYTHONPATH` / `MODELSCOPE_CACHE` / `HF_HOME`，并打印常用命令；不会自动录音或转写。不要用 `powershell -File .\scripts\run_env.ps1` 作为常规入口，因为那会在子进程里设置环境变量，后续命令可能吃不到缓存路径。

### 0. 启动常驻 STT server

在一个 PowerShell 窗口中运行：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\stt_server.py
```

服务只监听本机：

```text
http://127.0.0.1:8766
```

### 1. 一键录音 + server 自动转写 + 耗时诊断

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\listen_once.py --use-server --device 0 --seconds 5 --countdown 3 --channels 1 --samplerate 16000
```

输出至少包含：

- 保存路径
- `Peak amplitude`
- `RMS amplitude`
- 最终转写文本
- `record_seconds`
- `server_model_init_seconds`，仅表示服务启动时模型初始化耗时
- `transcribe_seconds`
- `total_seconds`

如果 server 不可用，`listen_once.py --use-server` 会清晰提示并直接退出，不再默认回退本地 STT。只有手动指定下面参数才允许回退：

```powershell
--allow-local-fallback
```

### 1.1 VAD 自动截断录音 + server 自动转写

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\listen_once.py --use-server --device 0 --vad --max-seconds 10 --silence-seconds 0.8 --countdown 3 --channels 1 --samplerate 16000
```

VAD 第一版只使用音量能量阈值，不接 Silero VAD 或 FunASR fsmn-vad。输出会额外包含：

- `actual_recording_seconds`
- `stop_reason`: `silence_after_speech` / `max_seconds_reached` / `no_speech_detected`
- `speech_detected`
- `energy_threshold`

如果环境噪声较高，可以让脚本先采样 0.5 秒环境噪声自动估计阈值：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\listen_once.py --use-server --device 0 --vad --calibrate-noise
```

### 1.2 控制台唤醒词原型

V0.6/V0.7/V0.8 的唤醒词不是最终 KWS 模型，而是“短录音 + STT 文本匹配”的可验证原型。V0.7.2 只优化这条文本匹配路径，没有训练 openWakeWord，也没有接 FunASR KWS：

```text
每 3 秒录一段短音频 -> STT server 转写 -> wake scoring -> 判定是否唤醒 -> VAD 录下一句话 -> STT server 转写命令
```

运行：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\wake_loop.py --device 0 --once --debug
```

常用参数：

- `--wake-window-seconds 3`: 等待阶段每次短录音窗口；短唤醒词“小黄”在 3 秒窗口下更稳定，但延迟略高
- `--wake-phrases 小黄,小黄小黄`: 逗号分隔的唤醒短语，实测建议优先说“小黄小黄”
- `--wake-aliases 小皇,小煌,小凰`: 逗号分隔的低置信别名，默认只包含低风险别名
- `--server-url http://127.0.0.1:8766`: 本地 STT server
- `--max-seconds 10`: 唤醒后命令句最长录音时间
- `--silence-seconds 0.8`: 唤醒后命令句静音停止阈值
- `--once`: 完成一次唤醒和命令转写后退出
- `--debug`: 打印等待阶段短音频识别文本
- `--keep-wake-recordings`: 保留等待唤醒阶段的短录音，默认不保留

debug 模式会输出唤醒匹配诊断：

```text
Wake check transcription: 小黄ang。
Wake match: detected=true score=0.90 reason=suffix_noise_match
```

`--wake-aliases` 用于覆盖/配置常见误识别，例如：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\wake_loop.py --device 0 --once --debug --wake-aliases 小王,小杨
```

不要把“小王”“小杨”这类宽泛别名默认打开，否则会增加误唤醒概率。

普通模式只输出阶段状态：

```text
Listening for wake phrase...
Wake word detected.
Listening for command...
Command transcription: ...
```

需要观察等待阶段每个短录音窗口的 STT 文本时，再加 `--debug`。

唤醒短音频默认保存到：

```text
data/recordings/wake/
```

V0.6.1 默认把这些短音频当作临时文件，调用 STT server 转写后会删除。若删除失败，脚本只打印 warning 并写日志，不会让主流程崩溃。需要保留短录音用于调试时，显式加：

```powershell
--keep-wake-recordings
```

这些真实音频即使保留，也已在 `.gitignore` 中忽略，不应提交。唤醒后的命令句录音仍保存在 `data/recordings/`，便于调试。

### 1.3 STT server 路径安全边界

V0.6.1 对 `/transcribe` 的 `wav_path` 加了本地路径 guard。STT server 只允许读取项目目录下：

```text
data/recordings/**/*.wav
```

会拒绝：

- 不存在的文件
- 非 `.wav` 后缀文件
- 通过 `..` 跳出目录的路径
- `data/recordings/` 之外的绝对路径

服务仍只监听 `127.0.0.1:8766`。这只是接 UI 前的本地安全边界，不代表已经开放远程访问。

### 1.4 音波悬浮窗 + 单句回复原型

V0.9 继续使用 Python 标准库 Tkinter 做轻量桌面悬浮窗，不引入 Electron、Node.js 或复杂 UI 依赖。它在 V0.8 规则回复基础上增加可选 DeepSeek 单句回复；不开启 `--enable-llm` 时保持本地规则回复逻辑。

运行：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug
```

启用 TTS：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug --enable-tts
```

启用 DeepSeek 单句回复：

```powershell
$env:DEEPSEEK_API_KEY="你的 key"
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug --enable-llm
```

启用 DeepSeek 单句回复 + TTS：

```powershell
$env:DEEPSEEK_API_KEY="你的 key"
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug --enable-llm --enable-tts
```

查看参数：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --help
```

窗口状态：

- `idle`: 小黄待机中 / 说“小黄”唤醒我
- `wake_checking`: 正在等待唤醒词
- `wake_detected`: 我在 / 请说你的命令
- `listening`: 正在听你说话
- `transcribing`: 识别中...
- `replying`: 正在想怎么回复...
- `speaking`: 小黄正在说话
- `result`: 你说：转写结果 / 小黄：规则回复
- `error`: 出错了 / 简短错误原因

DeepSeek 配置：

- `DEEPSEEK_API_KEY`: **必须通过环境变量设置**，不允许写入仓库或配置文件
- `DEEPSEEK_BASE_URL`: 可选，默认 `https://api.deepseek.com`
- `DEEPSEEK_MODEL`: 可选，默认 `deepseek-v4-flash`
- `--llm-timeout`: 默认 15 秒，网络超时、API 返回异常时自动 fallback
- `--llm-model`: 覆盖模型名
- `--llm-base-url`: 覆盖 base URL

如果启用 `--enable-llm` 但未配置 `DEEPSEEK_API_KEY`，不会崩溃，自动回退到本地规则回复。

debug 模式会显示回复来源：

```text
Reply source: llm
Reply source: rule
Reply source: rule_fallback_no_key
Reply source: rule_fallback_error
```

V0.9 只做单句回复，不保存历史上下文。V0.9.1 增加了回复后过滤：如果 LLM 返回"我已经打开""已下载""已执行"等虚假执行声明，会自动替换为：

```text
我可以先帮你整理任务，但当前版本还不能执行工具。
```

如果用户要求打开浏览器、发消息、写代码、下载资料、登录账号、支付等实际操作，小黄也只回复：

```text
我可以先帮你整理任务，但当前版本还不能执行工具。
```

规则回复仍保留作为 fallback：

```text
你好 / 你好小黄 -> 你好，我在。
你在干嘛 / 你想干嘛 -> 我在听你说话，准备帮你处理任务。
测试 -> 测试收到，语音链路正常。
其他 -> 我听到了：{用户文本}
```

TTS 使用 edge-tts 临时方案：

- 默认声音：`zh-CN-XiaoxiaoNeural`
- 输出目录：`data/tts/`
- 生成格式：mp3
- 依赖网络和微软 Edge Read Aloud 非官方接口
- `data/tts/` 已加入 `.gitignore`，不要提交生成音频
- 开启 `--enable-tts` 后默认会在回复后冷却 6 秒再继续监听，降低把自己的播放声录进 wake check 的概率

如果扬声器较大声，或者仍看到 TTS 尾音进入 `Wake check transcription`，可以加长冷却时间：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug --enable-tts --post-response-cooldown 8
```

启动前会检查：

```text
http://127.0.0.1:8766/health
```

如果 STT server 没启动，悬浮窗显示 `STT server 未启动`，控制台提示先运行：

```powershell
python scripts\stt_server.py --host 127.0.0.1 --port 8766
```

不会自动 fallback 到本地 STT，也不会自动启动 server。TTS 失败时只打印 warning 并显示错误状态，不会接入本地大模型或任务执行 fallback。

关闭悬浮窗可以直接关窗口或按 `Esc`。关闭时会设置后台循环停止标记，阻止后续 UI 更新，并在主窗口退出后短暂等待后台线程收尾；如果正处在一次短录音、VAD 录音或本地 HTTP 请求中，会在当前阻塞调用返回后结束。悬浮窗复用 `wake_loop_service.py`，等待唤醒阶段的短音频仍按 V0.6.1 策略默认删除，悬浮窗没有提供保留短录音的入口。

V0.6 原型缺点：

- 会频繁调用 STT server
- 资源占用比真正 KWS 高
- 唤醒延迟取决于 `--wake-window-seconds`
- 后续版本再评估 FunASR KWS 或 openWakeWord 自定义模型

### 1.5 V0.9 手动测试方式

终端 1：

```powershell
cd E:\Projects\xiaohuang
. .\scripts\run_env.ps1
& "F:\for_xiaohuang\conda310\python.exe" scripts\stt_server.py --host 127.0.0.1 --port 8766
```

终端 2：

```powershell
cd E:\Projects\xiaohuang
. .\scripts\run_env.ps1
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug
```

如果要测试 TTS 播放，用：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug --enable-tts
```

如果要测试 DeepSeek 回复，用：

```powershell
$env:DEEPSEEK_API_KEY="你的 key"
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --device 0 --debug --enable-llm --enable-tts
```

测试流程：

```text
1. 看到悬浮窗显示“小黄待机中”
2. 说“小黄”
3. 窗口显示“我在 / 请说你的命令”
4. 说“帮我测试一下悬浮窗”
5. 窗口显示“识别中”
6. 窗口显示“正在想怎么回复...”
7. 如果启用 `--enable-llm` 且 key 可用，DeepSeek 生成单句回复；否则使用规则回复
8. 窗口显示“你说：... / 小黄：...”
9. 如果开启 `--enable-tts`，窗口显示“小黄正在说话”并播放回复音频
10. 几秒后回到待机
```

### 2. 枚举麦克风

```powershell
cd E:\Projects\xiaohuang
$env:PYTHONPATH="E:\Projects\xiaohuang\src"
& "F:\for_xiaohuang\conda310\python.exe" scripts\check_audio_devices.py
```

输出会包含设备 ID、设备名称、最大输入通道数、默认采样率和推荐标记。包含 `麦克风` / `microphone` / `input` 的设备会标记为 `recommended`；包含 `speaker` / `output` / `立体声混音` 的设备会标记为 `not recommended`。

### 3. 录制 5 秒测试音频

使用默认输入设备：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\record_test.py
```

当前已验证可用设备是 `device 0`：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\record_test.py --device 0 --countdown 3
```

调整录音时长、通道数和采样率：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\record_test.py --device 0 --seconds 5 --channels 1 --samplerate 16000
```

录音会保存到：

```text
data/recordings/test_时间戳.wav
```

录音完成后会打印：

- `Peak amplitude`
- `RMS amplitude`
- 音量过低提示：可能录到静音或选错输入设备
- 削波提示：输入音量可能过大

### 4. 转写 WAV

当前推荐使用已安装 FunASR / SenseVoiceSmall 的 Python 环境运行：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\transcribe_test.py <wav_path>
```

例如：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\transcribe_test.py data\recordings\test_时间戳.wav
```

首次运行会下载或加载 SenseVoiceSmall 模型，耗时取决于网络和硬件。
如果当前 PATH 中没有 `ffmpeg`，脚本只会输出 warning：`ffmpeg not found, fallback to torchaudio for wav input`，不会强制要求安装 ffmpeg。

## 配置

默认配置在 `config/xiaohuang.yaml`：

- `audio.sample_rate`: 默认 `16000`
- `audio.channels`: 默认 `1`
- `audio.device_id`: 当前设置为 `0`，这是本机实测效果较好的麦克风设备
- `recording.duration_seconds`: 默认 `5`
- `recording.output_dir`: 默认 `data/recordings`
- `stt.model_name`: 默认 `iic/SenseVoiceSmall`

## 常见错误排查

### 找不到 sounddevice

执行：

```powershell
python -m pip install -r requirements.txt
```

### 没有麦克风设备

确认 Windows 麦克风权限已开启，并且系统声音设置中存在可用输入设备。

### 录音失败：Invalid device

先运行：

```powershell
python scripts\check_audio_devices.py
```

确认设备 ID 后，用 `--device <ID>` 指定。

### FunASR 未安装

执行：

```powershell
python -m pip install funasr modelscope torch torchaudio
```

如果仍失败，先完成 `check_audio_devices.py` 和 `record_test.py` 验证，再单独处理 STT 环境。

### 首次转写很慢

SenseVoiceSmall 首次运行可能下载模型并初始化 PyTorch。后续运行通常会更快。

## 后续方向

V0.9.1 收尾后，下一阶段建议：

- V1.0 Backend Foundation：构建后端服务基础，而不是直接接工具
- 后续再评估多轮上下文、托盘后台或真正 KWS
- 后续再评估 FunASR KWS 或 openWakeWord 自定义模型

当前仍未完成：

- 真正低功耗实时唤醒词模型
- 更完整的悬浮窗交互和托盘后台管理
- 离线 TTS 或更稳定的正式 TTS 方案
- 大模型单句回复和多轮对话
- 系统托盘
- 桌面安装器
- OpenCLI / opencode / QQ / 微信 / 爬虫等后续能力

## 版本控制注意

不要提交本地运行产物：

- `data/recordings/*.wav`
- `data/recordings/wake/`
- `logs/*.log`
- `logs/`
- `models/`
- `.venv/`
- `__pycache__/`
