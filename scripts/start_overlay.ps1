<#
.SYNOPSIS
    Start the XiaoHuang voice overlay in background.
.DESCRIPTION
    Launches voice_overlay.py with the project Python environment.
    Supports -Device, -EnableLlm, -EnableTts, -Debug switches.
    DEEPSEEK_API_KEY must be set by the user in the shell before running.
#>
param(
    [int]$Device = 0,
    [switch]$EnableLlm,
    [switch]$EnableTts,
    [switch]$Debug
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = "F:\for_xiaohuang\conda310\python.exe"
$LogDir = Join-Path $ProjectRoot "logs"

# load env
. "$ProjectRoot\scripts\run_env.ps1"

# warn if no LLM key
if ($EnableLlm -and (-not $env:DEEPSEEK_API_KEY)) {
    Write-Host "Note: DEEPSEEK_API_KEY is not set. LLM may fallback to local rule replies."
}

# ensure logs dir
New-Item -ItemType Directory -Force $LogDir | Out-Null

Write-Host "Starting voice overlay..."
$OutLogFile = Join-Path $LogDir "voice_overlay.out.log"
$ErrLogFile = Join-Path $LogDir "voice_overlay.err.log"
$ArgParts = @(
    "`"$ProjectRoot\scripts\voice_overlay.py`"",
    "--device", $Device
)
if ($EnableLlm)   { $ArgParts += "--enable-llm" }
if ($EnableTts)   { $ArgParts += "--enable-tts" }
if ($Debug)       { $ArgParts += "--debug" }

$ArgList = $ArgParts -join " "

Start-Process -FilePath $PythonExe -ArgumentList $ArgList -NoNewWindow -RedirectStandardOutput $OutLogFile -RedirectStandardError $ErrLogFile
Write-Host "Voice overlay starting (logs: $LogDir)"
