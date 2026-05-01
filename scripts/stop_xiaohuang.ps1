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

function Stop-ProjectProcess($Pattern) {
    $procs = Get-WmiObject Win32_Process -Filter "Name='python.exe'" | Where-Object {
        $_.CommandLine -match $Pattern -and $_.CommandLine -match [regex]::Escape($ProjectRoot)
    }
    foreach ($p in $procs) {
        Write-Host "Stopping $Pattern (PID=$($p.ProcessId))..."
        Stop-Process -Id $p.ProcessId -Force
    }
    if (-not $procs) {
        Write-Host "No $Pattern process found."
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
