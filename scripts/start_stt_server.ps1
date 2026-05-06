<#
.SYNOPSIS
    Start the XiaoHuang STT server in background.
.DESCRIPTION
    Checks if STT server is already running, then starts it using
    the project's conda Python environment. Logs to logs\stt_server.{out,err}.log.
#>
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = "F:\for_xiaohuang\conda310\python.exe"
$LogDir = Join-Path $ProjectRoot "logs"

# load env
$env:PYTHONPATH = "$ProjectRoot\src"
$env:MODELSCOPE_CACHE = "F:\for_xiaohuang\models\modelscope"
$env:HF_HOME = "F:\for_xiaohuang\models\huggingface"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# ensure logs dir
New-Item -ItemType Directory -Force $LogDir | Out-Null

# check if already running
try {
    $null = Invoke-RestMethod "http://127.0.0.1:8766/health" -TimeoutSec 2
    Write-Host "STT server already running on http://127.0.0.1:8766"
    exit 0
} catch {
    # not running, proceed
}

Write-Host "Starting STT server..."
$OutLogFile = Join-Path $LogDir "stt_server.out.log"
$ErrLogFile = Join-Path $LogDir "stt_server.err.log"
$ArgList = @(
    "`"$ProjectRoot\scripts\stt_server.py`"",
    "--host", "127.0.0.1",
    "--port", "8766"
) -join " "

Start-Process -FilePath $PythonExe -ArgumentList $ArgList -NoNewWindow -RedirectStandardOutput $OutLogFile -RedirectStandardError $ErrLogFile
Write-Host "STT server starting (logs: $LogDir)"
