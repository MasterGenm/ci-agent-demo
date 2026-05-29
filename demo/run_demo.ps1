param(
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Manifest = Get-Content -Path "demo/demo_manifest.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$MainTaskId = $Manifest.main_demo.task_id
$BackupTaskId = $Manifest.backup_demo.task_id

Write-Host "Starting cs-mvp dashboard on http://127.0.0.1:$Port"
Write-Host "Main demo:   http://127.0.0.1:$Port/runs/$MainTaskId"
Write-Host "Backup demo: http://127.0.0.1:$Port/runs/$BackupTaskId"
Write-Host ""

python -m cs_mvp.cli serve --host 127.0.0.1 --port $Port
