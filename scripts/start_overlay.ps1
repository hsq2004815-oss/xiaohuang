<#
.SYNOPSIS
    Start the XiaoHuang voice overlay in background.
.DESCRIPTION
    Launches voice_overlay.py with the project Python environment.
    Supports -Device, -EnableLlm, -EnableTts, -Debug switches.
    Loads DEEPSEEK_API_KEY from $env:USERPROFILE\.xiaohuang\secrets.ps1
    if not already set in the current shell.
#>
param(
    [int]$Device = 0,
    [switch]$EnableLlm,
    [switch]$EnableTts,
    [switch]$Debug,
    [switch]$ResidentHidden,
    [switch]$ConversationSession,
    [double]$SessionTimeout = 30,
    [int]$MaxSessionTurns = 5,
    [double]$FollowupTimeout = 10,
    [double]$MaxSessionSeconds = 90,
    [int]$MaxNoSpeechRetries = 1
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = "F:\for_xiaohuang\conda310\python.exe"
$LogDir = Join-Path $ProjectRoot "logs"

# load env
. "$ProjectRoot\scripts\run_env.ps1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# auto-load local secrets if key not already set
if (-not $env:DEEPSEEK_API_KEY) {
    $SecretFile = Join-Path $env:USERPROFILE ".xiaohuang\secrets.ps1"
    if (Test-Path $SecretFile) {
        . $SecretFile
        Write-Host "Loaded local secrets from $SecretFile"
    } else {
        Write-Host "No DEEPSEEK_API_KEY found. You may create: $SecretFile"
    }
}

# warn if no LLM key after loading secrets
if ($EnableLlm -and (-not $env:DEEPSEEK_API_KEY)) {
    Write-Host "Note: DEEPSEEK_API_KEY is not set. LLM may fallback to local rule replies."
}

# ensure logs dir
New-Item -ItemType Directory -Force $LogDir | Out-Null

# check for existing overlay processes
$ProjectPattern = [regex]::Escape($ProjectRoot)
$existing = @()
try {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop
    foreach ($p in $procs) {
        $cmd = $p.CommandLine
        if (-not $cmd) { continue }
        if ($cmd -notmatch $ProjectPattern) { continue }
        if ($cmd -match 'voice_overlay') {
            $existing += $p.ProcessId
        }
    }
} catch { }
if ($existing) {
    Write-Host "Voice overlay already running (PID: $($existing -join ', '))"
    exit 0
}

Write-Host "Starting voice overlay..."
$OutLogFile = Join-Path $LogDir "voice_overlay.out.log"
$ErrLogFile = Join-Path $LogDir "voice_overlay.err.log"
$ArgParts = @(
    "`"$ProjectRoot\scripts\voice_overlay.py`"",
    "--device", $Device
)
if ($EnableLlm)   { $ArgParts += "--enable-llm" }
if ($EnableTts)   { $ArgParts += "--enable-tts" }
if ($Debug)          { $ArgParts += "--debug" }
if ($ResidentHidden)       { $ArgParts += "--resident-hidden" }
if ($ConversationSession)  { $ArgParts += "--conversation-session" }
$ArgParts += @("--session-timeout", $SessionTimeout)
$ArgParts += @("--max-session-turns", $MaxSessionTurns)
$ArgParts += @("--followup-timeout", $FollowupTimeout)
$ArgParts += @("--max-session-seconds", $MaxSessionSeconds)
$ArgParts += @("--max-no-speech-retries", $MaxNoSpeechRetries)

$ArgList = $ArgParts -join " "

Start-Process -FilePath $PythonExe -ArgumentList $ArgList -NoNewWindow -RedirectStandardOutput $OutLogFile -RedirectStandardError $ErrLogFile
Write-Host "Voice overlay starting (logs: $LogDir)"
