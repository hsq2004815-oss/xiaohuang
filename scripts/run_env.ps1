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

Write-Host "XiaoHuang V0.1 environment is ready."
Write-Host "Project root: $ProjectRoot"
Write-Host "Python: $Python"
Write-Host "PYTHONPATH: $env:PYTHONPATH"
Write-Host "MODELSCOPE_CACHE: $env:MODELSCOPE_CACHE"
Write-Host "HF_HOME: $env:HF_HOME"
Write-Host ""
Write-Host "Common commands:"
Write-Host ""
Write-Host "Check audio devices:"
Write-Host "& `"$Python`" scripts\check_audio_devices.py"
Write-Host ""
Write-Host "Record 5 seconds with verified device 0:"
Write-Host "& `"$Python`" scripts\record_test.py --device 0 --seconds 5"
Write-Host ""
Write-Host "Transcribe latest recording:"
Write-Host "& `"$Python`" scripts\transcribe_test.py `"$latestRecording`""
Write-Host ""
Write-Host "This helper does not run recording or transcription automatically."
