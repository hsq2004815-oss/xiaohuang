<#
.SYNOPSIS
    Stop XiaoHuang processes.
.DESCRIPTION
    Stops the voice overlay process. Use -StopSttServer to also stop the STT server.
    Only kills processes whose command line matches this project.
#>
param(
    [switch]$StopSttServer
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Stop-ProjectProcess($ScriptName) {
    $pattern = $ScriptName -replace '\.', '\.'
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop
    } catch {
        Write-Host "Process query failed: $_"
        return
    }
    $killed = $false
    foreach ($p in $procs) {
        $cmd = $p.CommandLine
        if (-not $cmd) { continue }
        if ($cmd -notmatch [regex]::Escape($ProjectRoot)) { continue }
        if ($cmd -match $pattern) {
            Write-Host "Stopping $ScriptName (PID=$($p.ProcessId))..."
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Continue
            $killed = $true
        }
    }
    if (-not $killed) {
        Write-Host "No $ScriptName process found."
    }
}

Write-Host "=== Stopping voice overlay ==="
Stop-ProjectProcess "voice_overlay\.py"

if ($StopSttServer) {
    Write-Host "=== Stopping STT server ==="
    Stop-ProjectProcess "stt_server\.py"
} else {
    Write-Host "STT server left running (use -StopSttServer to stop it)."
}

Write-Host "Done."
