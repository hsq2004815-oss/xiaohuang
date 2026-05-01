<#
.SYNOPSIS
    Show XiaoHuang running status.
.DESCRIPTION
    Queries /health and lists running Python processes matching this project.
#>

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== STT Server Health ==="
try {
    $health = Invoke-RestMethod "http://127.0.0.1:8766/health" -TimeoutSec 3
    Write-Host "ok           : $($health.ok)"
    Write-Host "status       : $($health.status)"
    Write-Host "service      : $($health.service)"
    Write-Host "version      : $($health.version)"
    Write-Host "uptime_seconds: $($health.uptime_seconds)"
    Write-Host "model_loaded : $($health.model_loaded)"
    if ($health.last_error) {
        Write-Host "last_error   : code=$($health.last_error.code) message=$($health.last_error.message)"
    } else {
        Write-Host "last_error   : null"
    }
} catch {
    Write-Host "STT server not reachable on http://127.0.0.1:8766"
}

Write-Host ""
Write-Host "=== Python Processes ==="
$procs = Get-WmiObject Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -match "xiaohuang"
}
if ($procs) {
    foreach ($p in $procs) {
        $cmd = $p.CommandLine
        if ($cmd -match "voice_overlay") {
            Write-Host "voice_overlay : PID=$($p.ProcessId)"
        } elseif ($cmd -match "stt_server") {
            Write-Host "stt_server    : PID=$($p.ProcessId)"
        } else {
            Write-Host "xiaohuang     : PID=$($p.ProcessId)"
        }
    }
} else {
    Write-Host "No xiaohuang Python processes found."
}
