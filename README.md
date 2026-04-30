# 小黄 V0.6 控制台唤醒词原型

小黄是一个 Windows 桌面 AI 助手项目。当前 V0.6 在既有录音 + VAD + STT server 链路上增加控制台版唤醒词原型：持续短录音，使用 STT 文本匹配“小黄”，命中后进入 VAD 录音并转写下一句话。

```text
STT server 常驻 -> wake_loop 短录音 -> STT 文本匹配“小黄” -> VAD 录命令句 -> STT server 转写 -> 回到等待唤醒
```

## 当前范围

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
- `wake_loop.py` 默认要求 STT server 可用，不做本地 fallback

## 明确不包含

- 不训练真正的 openWakeWord 自定义模型
- 不接真正低功耗实时 KWS 模型
- 不做音波悬浮窗
- 不做 TTS
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

先用点执行加载 V0.6 本机运行环境，确保 `MODELSCOPE_CACHE` / `HF_HOME` 保留在当前 PowerShell 会话：

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

V0.6 当前成功测试结果：

```text
STT server 常驻可用
wake_loop.py --device 0 --once --debug 可进入等待状态
说“小黄”后可检测唤醒并输出 Wake word detected.
唤醒后进入 Listening for command...
命令句“帮我测试一下唤醒后的命令识别。”可进入 STT server 转写流程并输出 Command transcription
```

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

建议每次运行 V0.6 脚本前先点执行：

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

V0.6 的唤醒词不是最终 KWS 模型，而是“短录音 + STT 文本匹配”的可验证原型：

```text
每 2 秒录一段短音频 -> STT server 转写 -> 文本包含“小黄”则判定唤醒 -> VAD 录下一句话 -> STT server 转写命令
```

运行：

```powershell
& "F:\for_xiaohuang\conda310\python.exe" scripts\wake_loop.py --device 0 --once --debug
```

常用参数：

- `--wake-window-seconds 2`: 等待阶段每次短录音窗口
- `--wake-phrases 小黄,小黄小黄`: 逗号分隔的唤醒短语
- `--server-url http://127.0.0.1:8766`: 本地 STT server
- `--max-seconds 10`: 唤醒后命令句最长录音时间
- `--silence-seconds 0.8`: 唤醒后命令句静音停止阈值
- `--once`: 完成一次唤醒和命令转写后退出
- `--debug`: 打印等待阶段短音频识别文本

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

这些真实音频已在 `.gitignore` 中忽略，不应提交。

V0.6 原型缺点：

- 会频繁调用 STT server
- 资源占用比真正 KWS 高
- 唤醒延迟取决于 `--wake-window-seconds`
- 后续 V0.7/V0.8 再评估 FunASR KWS 或 openWakeWord 自定义模型

### 1.3 V0.6 手动测试方式

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
& "F:\for_xiaohuang\conda310\python.exe" scripts\wake_loop.py --device 0 --once --debug
```

测试说法：

```text
先说：小黄
检测到 Wake word detected. 后，再说：帮我测试一下唤醒后的命令识别。
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

V0.6 跑通后，再进入：

- V0.7：接入音波悬浮窗
- V0.8：整合为后台托盘程序
- 后续再评估 FunASR KWS 或 openWakeWord 自定义模型

当前仍未完成：

- 真正低功耗实时唤醒词模型
- 音波悬浮窗
- TTS
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
