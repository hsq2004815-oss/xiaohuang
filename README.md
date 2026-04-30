# 小黄 V0.1 最小音频链路验证

小黄是一个 Windows 桌面 AI 助手项目。当前 V0.1 只验证最小音频链路：

```text
麦克风录音 -> 保存 WAV -> 固定 5 秒截断 -> FunASR / SenseVoiceSmall 转文字 -> 控制台输出
```

## 当前范围

- 枚举 Windows 当前可用麦克风
- 选择麦克风设备录制固定时长音频
- 保存 WAV 到 `data/recordings/`
- 预留 VAD 接口，但 V0.1 默认只做固定 5 秒录音
- 通过 FunASR SenseVoiceSmall 转写 WAV 文件
- 脚本日志输出到 `logs/`

## 明确不包含

- 不接唤醒词“小黄”
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

### 1. 枚举麦克风

```powershell
cd E:\Projects\xiaohuang
$env:PYTHONPATH="E:\Projects\xiaohuang\src"
python scripts\check_audio_devices.py
```

输出会包含设备 ID、设备名称、最大输入通道数和默认采样率。

### 2. 录制 5 秒测试音频

使用默认输入设备：

```powershell
python scripts\record_test.py
```

选择指定设备：

```powershell
python scripts\record_test.py --device 1
```

调整录音时长：

```powershell
python scripts\record_test.py --device 1 --seconds 5
```

录音会保存到：

```text
data/recordings/test_时间戳.wav
```

### 3. 转写 WAV

```powershell
python scripts\transcribe_test.py data\recordings\test_时间戳.wav
```

首次运行会下载或加载 SenseVoiceSmall 模型，耗时取决于网络和硬件。

## 配置

默认配置在 `config/xiaohuang.yaml`：

- `audio.sample_rate`: 默认 `16000`
- `audio.channels`: 默认 `1`
- `audio.device_id`: 默认 `null`，表示使用系统默认输入设备
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

V0.1 跑通后，再进入：

- V0.2：接入唤醒词“小黄”
- V0.3：优化 STT 和 VAD
- V0.4：接入音波悬浮窗
- V0.5：整合为后台托盘程序
