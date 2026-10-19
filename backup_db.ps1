# -*- coding: utf-8 -*-
# Backup of the SQLite database (safe with WAL: uses SQLite's own backup API).
#
# Usage:
#   .\backup_db.ps1
#   .\backup_db.ps1 -Keep 14          # keep last 14 backups
#   .\backup_db.ps1 -Db "data\app.db" -Out "data\backups"

param(
    [string]$Db = "data\app.db",
    [string]$Out = "data\backups",
    [int]$Keep = 7
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location -LiteralPath $root

$dbPath = Join-Path $root $Db
if (-not (Test-Path -LiteralPath $dbPath)) {
    Write-Host "[!] Database not found: $dbPath" -ForegroundColor Red
    exit 1
}

$outDir = Join-Path $root $Out
if (-not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$py = Join-Path $root ".venv312\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) { $py = "python" }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $outDir "app-$stamp.db"

$script = @'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
print("ok")
'@

$tmp = Join-Path $env:TEMP "backup_db_$stamp.py"
Set-Content -LiteralPath $tmp -Value $script -Encoding UTF8
try {
    & $py $tmp $dbPath $target | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "backup failed" }
} finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}

$size = [Math]::Round((Get-Item -LiteralPath $target).Length / 1MB, 2)
Write-Host "[+] Backup created: $target (${size} MB)" -ForegroundColor Green

if ($Keep -gt 0) {
    $old = Get-ChildItem -LiteralPath $outDir -Filter "app-*.db" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $Keep
    foreach ($f in $old) {
        Remove-Item -LiteralPath $f.FullName -Force
        Write-Host "[*] Removed old backup: $($f.Name)" -ForegroundColor DarkGray
    }
}
