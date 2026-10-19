# -*- coding: utf-8 -*-
# Installs the bot as a Windows Scheduled Task that starts at logon and
# restarts automatically - no window needs to stay open.
#
# Run once (PowerShell as Administrator is NOT required for a user task):
#   .\install_autostart.ps1
#
# Remove:
#   .\install_autostart.ps1 -Uninstall
#
# Check:
#   Get-ScheduledTask -TaskName "SereneClinicBot"

param(
    [string]$TaskName = "SereneClinicBot",
    [switch]$Uninstall,
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$watchdog = Join-Path $root "run_forever.ps1"

if ($Uninstall) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[+] Removed scheduled task: $TaskName" -ForegroundColor Green
    } else {
        Write-Host "[i] Task not found: $TaskName" -ForegroundColor Yellow
    }
    return
}

if (-not (Test-Path -LiteralPath $watchdog)) {
    throw "Missing run_forever.ps1 next to this script."
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdog`"" `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Serene Clinic cyber-academy Telegram bot (24/7 watchdog)" `
    -Force | Out-Null

Write-Host "[+] Installed scheduled task: $TaskName" -ForegroundColor Green
Write-Host "    Starts at logon, restarts on failure, runs hidden." -ForegroundColor Gray
Write-Host "    Logs: data\logs\watchdog.log and data\logs\bot.log" -ForegroundColor Gray

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[*] Task started." -ForegroundColor Cyan
}
