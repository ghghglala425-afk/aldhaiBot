# -*- coding: utf-8 -*-
# Keeps the bot running 24/7: restarts automatically if it crashes.
#
# Usage:
#   .\run_forever.ps1
#   .\run_forever.ps1 -RestartDelay 10 -MaxRestarts 0
#
# Stop: Ctrl+C (or close the window).

param(
    [int]$RestartDelay = 10,
    [int]$MaxRestarts = 0,          # 0 = unlimited
    [int]$MaxBackoff = 300,
    [string]$Python = "",
    [string]$DatabaseUrl = "sqlite+aiosqlite:///./data/app.db"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location -LiteralPath $root

$venvPy = Join-Path $root ".venv312\Scripts\python.exe"
if (-not $Python) {
    if (Test-Path -LiteralPath $venvPy) { $Python = $venvPy } else { $Python = "py -3.12" }
}
$pyParts = $Python -split "\s+"
$pyExe = $pyParts[0]
$pyArgs = @()
if ($pyParts.Length -gt 1) { $pyArgs = $pyParts[1..($pyParts.Length - 1)] }

$env:DISABLE_SQLALCHEMY_CEXT = "1"
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = $DatabaseUrl }
if (-not $env:VERIFY_EXEC) { $env:VERIFY_EXEC = "0" }
if (-not $env:PYTHONIOENCODING) { $env:PYTHONIOENCODING = "utf-8" }
if (-not $env:PYTHONUNBUFFERED) { $env:PYTHONUNBUFFERED = "1" }

$logDir = Join-Path $root "data\logs"
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$watchdogLog = Join-Path $logDir "watchdog.log"

function Write-Log([string]$msg) {
    $line = "{0} | {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -LiteralPath $watchdogLog -Value $line -Encoding UTF8
}

Write-Log "== Bot watchdog starting (python: $Python) =="

$restarts = 0
$backoff = $RestartDelay

while ($true) {
    $started = Get-Date
    Write-Log "Starting bot..."
    try {
        & $pyExe @pyArgs -m app.bot
        $code = $LASTEXITCODE
    } catch {
        Write-Log "Launch error: $_"
        $code = -1
    }
    $ran = [int]((Get-Date) - $started).TotalSeconds
    Write-Log "Bot exited (code=$code) after ${ran}s."

    if ($MaxRestarts -gt 0 -and $restarts -ge $MaxRestarts) {
        Write-Log "Reached MaxRestarts=$MaxRestarts - stopping."
        break
    }

    # Clean long run resets the backoff.
    if ($ran -ge 300) { $backoff = $RestartDelay }
    $restarts++
    Write-Log "Restarting in ${backoff}s (restart #$restarts)..."
    Start-Sleep -Seconds $backoff
    $backoff = [Math]::Min($backoff * 2, $MaxBackoff)
}
