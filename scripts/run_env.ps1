$ProjectRoot = "E:\Projects\xiaohuang"
$Python = "F:\for_xiaohuang\conda310\python.exe"

Set-Location -LiteralPath $ProjectRoot

$env:PYTHONPATH = "E:\Projects\xiaohuang\src"
$env:MODELSCOPE_CACHE = "F:\for_xiaohuang\models\modelscope"
$env:HF_HOME = "F:\for_xiaohuang\models\huggingface"

$latestRecording = "data\recordings\test_时间戳.wav"
$existingRecording = Get-ChildItem -LiteralPath "data\recordings" -Filter "*.wav" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($existingRecording) {
    $latestRecording = $existingRecording.FullName
}

Write-Host "XiaoHuang V0.7 voice-overlay prototype environment is ready."
Write-Host "Project root: $ProjectRoot"
Write-Host "Python: $Python"
Write-Host "PYTHONPATH: $env:PYTHONPATH"
Write-Host "MODELSCOPE_CACHE: $env:MODELSCOPE_CACHE"
Write-Host "HF_HOME: $env:HF_HOME"
Write-Host ""
Write-Host "Recommended usage: dot-source this script so env vars stay in the current PowerShell session:"
Write-Host ". .\scripts\run_env.ps1"
Write-Host ""
Write-Host "Common commands:"
Write-Host ""
Write-Host "Check audio devices:"
Write-Host "& `"$Python`" scripts\check_audio_devices.py"
Write-Host ""
Write-Host "Record 5 seconds with verified device 0:"
Write-Host "& `"$Python`" scripts\record_test.py --device 0 --seconds 5 --countdown 3 --channels 1 --samplerate 16000"
Write-Host ""
Write-Host "Listen once: record, transcribe, and print timing diagnostics:"
Write-Host "& `"$Python`" scripts\listen_once.py --device 0 --seconds 5 --countdown 3 --channels 1 --samplerate 16000"
Write-Host ""
Write-Host "Start local STT server:"
Write-Host "& `"$Python`" scripts\stt_server.py"
Write-Host ""
Write-Host "Listen once using the local STT server:"
Write-Host "& `"$Python`" scripts\listen_once.py --use-server --server-url http://127.0.0.1:8766 --device 0 --seconds 5 --countdown 3 --channels 1 --samplerate 16000"
Write-Host ""
Write-Host "Listen once with VAD automatic cutoff using the local STT server:"
Write-Host "& `"$Python`" scripts\listen_once.py --use-server --server-url http://127.0.0.1:8766 --device 0 --vad --max-seconds 10 --silence-seconds 0.8 --countdown 3 --channels 1 --samplerate 16000"
Write-Host ""
Write-Host "Console wake-word prototype, one command after wake:"
Write-Host "& `"$Python`" scripts\wake_loop.py --device 0 --once --debug"
Write-Host ""
Write-Host "Voice overlay prototype:"
Write-Host "& `"$Python`" scripts\voice_overlay.py --device 0 --debug"
Write-Host ""
Write-Host "Transcribe latest recording through the local STT server:"
Write-Host "& `"$Python`" scripts\stt_client.py --server-url http://127.0.0.1:8766 `"$latestRecording`""
Write-Host ""
Write-Host "Transcribe latest recording:"
Write-Host "& `"$Python`" scripts\transcribe_test.py `"$latestRecording`""
Write-Host ""
Write-Host "This helper does not run recording or transcription automatically."
