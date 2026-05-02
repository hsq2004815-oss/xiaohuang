<#
.SYNOPSIS
    One-click start XiaoHuang: STT server + voice overlay.
.DESCRIPTION
    Starts the STT server first, waits for /health ready (up to 60s),
    then launches the voice overlay. Accepts the same switches as start_overlay.ps1.
#>
param(
    [int]$Device = 0,
    [switch]$EnableLlm,
    [switch]$EnableTts,
    [switch]$Debug,
    [switch]$ResidentHidden,
    [switch]$ConversationSession,
    [double]$SessionTimeout = 30,
    [int]$MaxSessionTurns = 5
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# 1. start STT server
Write-Host "--- Starting STT server ---"
& "$PSScriptRoot\start_stt_server.ps1"

# 2. wait for /health
Write-Host "Waiting for STT server health check..."
$MaxWait = 60
$Elapsed = 0
while ($Elapsed -lt $MaxWait) {
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:8766/health" -TimeoutSec 2
        if ($health.ok) {
            Write-Host "STT server ready: status=$($health.status) model_loaded=$($health.model_loaded) uptime=$($health.uptime_seconds)s"
            break
        }
    } catch {
        # not ready yet
    }
    Start-Sleep -Seconds 2
    $Elapsed += 2
}
if ($Elapsed -ge $MaxWait) {
    Write-Host "ERROR: STT server did not become ready within ${MaxWait}s. Check logs\stt_server.err.log"
    exit 1
}

# 3. start overlay
Write-Host "--- Starting voice overlay ---"
$OverlayParams = @{
    Device = $Device
}
if ($EnableLlm)      { $OverlayParams.EnableLlm = $true }
if ($EnableTts)      { $OverlayParams.EnableTts = $true }
if ($Debug)          { $OverlayParams.Debug = $true }
if ($ResidentHidden)       { $OverlayParams.ResidentHidden = $true }
if ($ConversationSession)  { $OverlayParams.ConversationSession = $true }
$OverlayParams.SessionTimeout = $SessionTimeout
$OverlayParams.MaxSessionTurns = $MaxSessionTurns

& "$PSScriptRoot\start_overlay.ps1" @OverlayParams

Write-Host ""
Write-Host "=== XiaoHuang started ==="
Write-Host "STT server : http://127.0.0.1:8766"
Write-Host "Logs       : $ProjectRoot\logs\"
