# Task Memory

- Purpose: XiaoHuang V0.6 adds a console wake-word prototype using short-window STT text matching before the existing VAD + STT command flow.
- Key files: `scripts/wake_loop.py`, `src/xiaohuang/wake_word_service.py`, `src/xiaohuang/stt_client_service.py`, `src/xiaohuang/vad_recording_service.py`, `scripts/stt_server.py`.
- Current environment: use `F:\for_xiaohuang\conda310\python.exe`; recording works with `device 0`; ModelScope cache is `F:\for_xiaohuang\models\modelscope`; ffmpeg is installed through `winget` and available on PATH.
- Startup/test: dot-source `.\scripts\run_env.ps1`; set `PYTHONPATH=E:\Projects\xiaohuang\src`; run `& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests`.
- Last completed: V0.6 `wake_loop.py` records short wake windows, sends them to STT server, matches `小黄`/`小黄小黄`, then records one VAD command and transcribes it.
- Server fallback policy: `listen_once.py --use-server` requires the resident server by default; add `--allow-local-fallback` only when local direct STT fallback is acceptable.
- Recommended VAD command: `& "F:\for_xiaohuang\conda310\python.exe" scripts\listen_once.py --use-server --device 0 --vad --max-seconds 10 --silence-seconds 0.8 --countdown 3 --channels 1 --samplerate 16000`.
- Recommended wake-loop command: `& "F:\for_xiaohuang\conda310\python.exe" scripts\wake_loop.py --device 0 --once --debug`.
- Current usable STT server command: `& "F:\for_xiaohuang\conda310\python.exe" scripts\stt_server.py --host 127.0.0.1 --port 8766`.
- Current successful wake test: start STT server, run `wake_loop.py --device 0 --once --debug`, say `小黄`, then say `帮我测试一下唤醒后的命令识别。`; expected state output includes `Listening for wake phrase...`, `Wake word detected.`, `Listening for command...`, and `Command transcription: ...`.
- Verified output example from earlier STT baseline: input speech `小黄小黄帮我测试一下语音识别功能，我们正在开发语音识别助手。`; output text matched the same sentence.
- Git ignore boundary: do not commit `data/recordings/*.wav`, `data/recordings/wake/`, `logs/`, `models/`, `.venv/`, or `__pycache__/`.
- Known traps: V0.6 wake is only STT text matching, not a low-power KWS model; it frequently calls STT server and depends on `--wake-window-seconds` latency.
- Still unfinished: real KWS model, waveform overlay, TTS, system tray, installer, and later desktop-assistant integrations.
- Next likely edit points: tune `--wake-window-seconds`, wake phrase matching, `energy_threshold`, and `silence_seconds` against real microphone conditions.
