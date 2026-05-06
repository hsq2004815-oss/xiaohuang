# V1.3 PySide6 Voice Dock + GPU STT Acceptance Record

Date: 2026-05-06
Status: accepted by human runtime validation
Scope: V1.3 voice overlay rendering, openWakeWord wake pipeline, and GPU STT acceptance

## Environment

- OS: Windows
- Python: `F:\for_xiaohuang\conda310\python.exe`
- PySide6: 6.11.0
- torch: 2.10.0+cu126
- torchaudio: 2.10.0+cu126
- GPU: NVIDIA GeForce RTX 4050 Laptop GPU
- Wake engine: openwakeword
- Wake phrase: hey jarvis

## STT Health

- /health status: ready
- model_loaded: True
- stt_device: cuda:0
- server_model_init_seconds: about 27.68s in this acceptance run

## GPU Validation

- nvidia-smi showed `F:\for_xiaohuang\conda310\python.exe` using GPU memory
- GPU memory usage was about 1.7GB in this acceptance run

## End-to-End Acceptance

- hey jarvis wake succeeded
- openwakeword_wake_event label=hey_jarvis
- command_record_start source=openwakeword
- Overlay command transcription returned text
- Overlay reply source=llm
- TTS playback worked
- PySide6 waveform dock appeared correctly
- No white background, black background, gray frame, or rounded panel remained

## User Confirmation

The transparent PySide6 waveform dock effect met the expected visual and runtime behavior. The voice overlay, wake pipeline, STT, LLM, and TTS all functioned correctly in the end-to-end test.

## Final Technical Route

- Voice overlay: PySide6 / QWidget / QPainter
- Control panel: pywebview / web frontend (frontend/control_panel/*)
- STT: FunASR SenseVoiceSmall, device configurable (cpu / cuda:0)
- LLM: DeepSeek API
- TTS: edge-tts

## Regression Risks

- Do not restore pywebview voice overlay
- Do not reintroduce background frame / border / rounded panel in `src/xiaohuang/voice_overlay_qt_ui.py`
- Do not hard-code STT device to cpu or cuda:0 — keep configurable device + fallback behavior
- Do not revert the voice overlay to Tkinter cyber HUD / Canvas / Pillow implementation

## Verification Commands

```powershell
cd E:\Projects\xiaohuang
$env:PYTHONPATH = "E:\Projects\xiaohuang\src"
$env:PYTHONDONTWRITEBYTECODE = "1"

# compile check
& "F:\for_xiaohuang\conda310\python.exe" -m compileall -q src scripts tests

# unit tests
& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests

# STT server help
& "F:\for_xiaohuang\conda310\python.exe" scripts\stt_server.py --help

# voice overlay help
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --help

# GPU check
& "F:\for_xiaohuang\conda310\python.exe" -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"

# STT health
Invoke-RestMethod http://127.0.0.1:8766/health
```
