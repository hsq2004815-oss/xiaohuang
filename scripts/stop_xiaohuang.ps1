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
$ProjectPattern = [regex]::Escape($ProjectRoot)

function Get-XiaoHuangProcesses {
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop
    } catch {
        return @()
    }
    $result = @()
    foreach ($p in $procs) {
        $cmd = $p.CommandLine
        if (-not $cmd) { continue }
        if ($cmd -notmatch $ProjectPattern -and $cmd -notmatch 'xiaohuang') { continue }
        if ($cmd -match 'voice_overlay') {
            $result += [PSCustomObject]@{ ProcessId = $p.ProcessId; Type = 'voice_overlay' }
        } elseif ($cmd -match 'stt_server') {
            $result += [PSCustomObject]@{ ProcessId = $p.ProcessId; Type = 'stt_server' }
        } elseif ($cmd -match 'xiaohuang') {
            $result += [PSCustomObject]@{ ProcessId = $p.ProcessId; Type = 'xiaohuang' }
        }
    }
    return $result
}

function Stop-ByType($Type) {
    $procs = Get-XiaoHuangProcesses | Where-Object { $_.Type -eq $Type }
    if (-not $procs) {
        Write-Host "No $Type process found."
        return
    }
    foreach ($p in $procs) {
        Write-Host "Stopping $($p.Type) (PID=$($p.ProcessId))..."
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Continue
    }
}

Write-Host "=== Stopping voice overlay ==="
Stop-ByType "voice_overlay"

if ($StopSttServer) {
    Write-Host "=== Stopping STT server ==="
    Stop-ByType "stt_server"
} else {
    Write-Host "STT server left running (use -StopSttServer to stop it)."
}

Write-Host "Done."
