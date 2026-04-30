# XiaoHuang Memory

- Project: `E:\Projects\xiaohuang`
- Current version: V0.1 minimal audio pipeline validation.
- Current goal: microphone device listing, fixed-duration WAV recording, and FunASR / SenseVoiceSmall transcription from an existing WAV.
- Main scripts:
  - `scripts/check_audio_devices.py`
  - `scripts/record_test.py`
  - `scripts/transcribe_test.py`
- Main services:
  - `src/xiaohuang/audio_capture_service.py`
  - `src/xiaohuang/vad_service.py`
  - `src/xiaohuang/stt_service.py`
  - `src/xiaohuang/config_service.py`
  - `src/xiaohuang/logging_service.py`
- Setup: create a project-local venv or conda env, then run `python -m pip install -r requirements.txt`.
- STT setup: install `funasr modelscope torch torchaudio` separately when ready to validate SenseVoiceSmall.
- Verification used: unit tests, compileall, and CLI help checks.
- Known gap: real microphone capture and FunASR transcription have not been validated until dependencies and hardware are available.
- Do not add in V0.1: wake word, overlay UI, TTS, OpenCLI, opencode, QQ/WeChat, browser automation, crawler, downloader, or task scheduler.

