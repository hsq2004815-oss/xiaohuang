# XiaoHuang Runbook

## Quick Start

1. Open PowerShell.
2. Go to project root: `cd E:\Projects\xiaohuang`
3. Set environment:
   ```powershell
   $env:PYTHONPATH = "E:\Projects\xiaohuang\src"
   $env:PYTHONDONTWRITEBYTECODE = "1"
   ```
4. Start STT server:
   ```powershell
   & "F:\for_xiaohuang\conda310\python.exe" .\scripts\stt_server.py --host 127.0.0.1 --port 8766
   ```
5. Check STT health:
   ```powershell
   Invoke-RestMethod http://127.0.0.1:8766/health
   ```
6. Start web control panel:
   ```powershell
   & "F:\for_xiaohuang\conda310\python.exe" .\scripts\control_panel_web.py
   ```
7. Start XiaoHuang from the control panel.
8. Wake with "hey jarvis".

## Commands

### Start STT server

```powershell
cd E:\Projects\xiaohuang
$env:PYTHONPATH = "E:\Projects\xiaohuang\src"
$env:PYTHONDONTWRITEBYTECODE = "1"

& "F:\for_xiaohuang\conda310\python.exe" .\scripts\stt_server.py --host 127.0.0.1 --port 8766
```

### Check STT health

```powershell
Invoke-RestMethod http://127.0.0.1:8766/health
```

Expected response: `status = ready`, `model_loaded = True`, `stt_device = cpu` (or `cuda:0`).

### Start control panel

```powershell
cd E:\Projects\xiaohuang
$env:PYTHONPATH = "E:\Projects\xiaohuang\src"
$env:PYTHONDONTWRITEBYTECODE = "1"

& "F:\for_xiaohuang\conda310\python.exe" .\scripts\control_panel_web.py
```

### Start voice overlay directly

```powershell
cd E:\Projects\xiaohuang
$env:PYTHONPATH = "E:\Projects\xiaohuang\src"
$env:PYTHONDONTWRITEBYTECODE = "1"

& "F:\for_xiaohuang\conda310\python.exe" .\scripts\voice_overlay.py --debug --resident-hidden --conversation-session --enable-llm --enable-tts
```

## LLM Key

Use environment variable:

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
```

Do not commit real keys to config files or Git.

## GPU STT Check

```powershell
& "F:\for_xiaohuang\conda310\python.exe" -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
nvidia-smi
Invoke-RestMethod http://127.0.0.1:8766/health
```

## Verification

```powershell
cd E:\Projects\xiaohuang
$env:PYTHONPATH = "E:\Projects\xiaohuang\src"
$env:PYTHONDONTWRITEBYTECODE = "1"

# compile check
& "F:\for_xiaohuang\conda310\python.exe" -m compileall -q src scripts tests

# unit tests
& "F:\for_xiaohuang\conda310\python.exe" -m unittest discover -s tests

# help checks
& "F:\for_xiaohuang\conda310\python.exe" scripts\voice_overlay.py --help
& "F:\for_xiaohuang\conda310\python.exe" scripts\stt_server.py --help
```

## Common Problems

- **STT server unavailable**: start `stt_server.py` first.
- **LLM API key missing**: set `DEEPSEEK_API_KEY` in the same process/session that launches XiaoHuang.
- **resident_hidden=true**: idle overlay may be hidden until wake.
- **Old voice_overlay.py process remains**: kill XiaoHuang Python processes.
- **stt.device=cuda:0 but CUDA unavailable**: STT server should fallback to cpu.
- **edge-tts requires network**: TTS needs internet access.

## Stop All XiaoHuang Processes

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -match "xiaohuang|voice_overlay|stt_server|control_panel" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## Do Not Commit

- `.claude/`
- `overlay_ui_context.txt`
- `logs/`
- `data/recordings/`
- `data/tts/`
- `secrets.ps1`
- API keys
