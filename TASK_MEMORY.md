# Task Memory

- Purpose: XiaoHuang V0.1 validates the minimal Windows audio path only: device listing, fixed-duration WAV recording, and FunASR/SenseVoiceSmall transcription entrypoint.
- Key files: `scripts/check_audio_devices.py`, `scripts/record_test.py`, `scripts/transcribe_test.py`, `src/xiaohuang/audio_capture_service.py`, `src/xiaohuang/stt_service.py`.
- Startup/test: set `PYTHONPATH=E:\Projects\xiaohuang\src`; run `python -m unittest discover -s tests`.
- Last completed: project skeleton, config, logging, fixed-duration VAD placeholder, device listing, recording script, transcription script, README.
- Verification: unit tests passed; compileall passed; CLI help for record/transcribe passed; device listing reported missing `sounddevice` until requirements are installed.
- Known traps: do not add wake word, overlay UI, TTS, OpenCLI, opencode, QQ/WeChat, crawlers, or task scheduling in V0.1.
- Next likely edit points: install project deps in a venv, run `check_audio_devices.py`, record a 5-second WAV, then install FunASR stack and run `transcribe_test.py`.
