# Task Memory

- Purpose: XiaoHuang V0.1 validates the minimal Windows audio path only: device listing, fixed-duration WAV recording, and FunASR/SenseVoiceSmall transcription entrypoint.
- Key files: `scripts/check_audio_devices.py`, `scripts/record_test.py`, `scripts/transcribe_test.py`, `src/xiaohuang/audio_capture_service.py`, `src/xiaohuang/stt_service.py`.
- Current environment: use `F:\for_xiaohuang\conda310\python.exe`; ModelScope cache is `F:\for_xiaohuang\models\modelscope`; ffmpeg is installed through `winget` and available on PATH.
- Startup/test: set `PYTHONPATH=E:\Projects\xiaohuang\src`; run `& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests`.
- Last completed: V0.1 end-to-end manual validation with `device 0` microphone recording and FunASR / SenseVoiceSmall Chinese transcription.
- Verified commands: `& "F:\for_xiaohuang\conda310\python.exe" scripts\check_audio_devices.py`; `& "F:\for_xiaohuang\conda310\python.exe" scripts\record_test.py --device 0 --seconds 5`; `& "F:\for_xiaohuang\conda310\python.exe" scripts\transcribe_test.py <wav_path>`.
- Verified output example: input speech `小黄小黄帮我测试一下语音识别功能，我们正在开发语音识别助手。`; output text matched the same sentence.
- Known traps: do not add wake word, overlay UI, TTS, OpenCLI, opencode, QQ/WeChat, crawlers, or task scheduling in V0.1.
- Still unfinished: wake word, waveform overlay, VAD automatic cutoff, TTS, system tray, installer, and later desktop-assistant integrations.
- Next likely edit points: document or automate repeatable V0.1 validation, then plan V0.2 wake-word work only after preserving the proven audio/STT baseline.
