# V1.3 PySide6 Transparent Voice Dock Acceptance Record

Date: 2026-05-06
Status: accepted by human runtime validation
Scope: V1.3 voice overlay rendering and main voice pipeline acceptance

## Acceptance Environment

- OS: Windows
- Python: `F:\for_xiaohuang\conda310\python.exe`
- PySide6: 6.11.0
- Wake engine: `openwakeword`
- Wake phrase: `hey jarvis`

## Human Acceptance Results

The V1.3 PySide6 transparent voice dock was manually accepted after running the real desktop workflow, not only a preview smoke test.

Accepted items:

- Control panel can start XiaoHuang.
- STT server is reachable by the overlay runtime.
- `hey jarvis` triggers the `openwakeword` wake engine.
- Command recording starts after wake detection.
- STT transcription returns command text.
- LLM reply source is `llm` when `DEEPSEEK_API_KEY` is configured.
- TTS playback works after the reply is generated.
- PySide6 waveform dock appears without a background frame.
- Waveform changes across listening, transcribing, replying, and speaking states.
- `resident_hidden=true` hides the overlay after the session returns to idle.

User confirmation: the transparent PySide6 waveform dock effect met the expected visual and runtime behavior.

## Stage Boundaries

- The voice overlay is no longer hosted through `pywebview`.
- Tkinter Canvas/Pillow is no longer the final rendering path for the voice overlay.
- The control panel may continue to use web/pywebview surfaces where appropriate.
- This record does not authorize changes to wake detection, STT, LLM, TTS, or control panel runtime logic.

## Regression Risks

- Do not reintroduce `drawRoundedRect`, `fillRect`, or `fillPath` background panels in `src/xiaohuang/voice_overlay_qt_ui.py`.
- Do not reintroduce WebView voice overlay white-background behavior.
- Do not revert the voice overlay to the Tkinter cyber HUD implementation.
- Do not add a gray rounded container, border line, white fill, black fill, glass panel, shadow card, or QWidget stylesheet background around the waveform.

## Future Check Commands

Run from `E:\Projects\xiaohuang`:

```powershell
$env:PYTHONPATH = "E:\Projects\xiaohuang\src"
$env:PYTHONDONTWRITEBYTECODE = "1"

& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --help
& "F:\for_xiaohuang\conda310\python.exe" -m compileall -q src scripts tests
& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests
```

STT server startup:

```powershell
cd E:\Projects\xiaohuang
. .\scripts\run_env.ps1
& "F:\for_xiaohuang\conda310\python.exe" scripts\stt_server.py --host 127.0.0.1 --port 8766
```

Voice overlay debug startup:

```powershell
cd E:\Projects\xiaohuang
. .\scripts\run_env.ps1
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --debug --resident-hidden --conversation-session --enable-llm --enable-tts
```
