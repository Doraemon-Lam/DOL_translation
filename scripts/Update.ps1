param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskBin = Join-Path $taskRoot 'bin'
if (-not (Test-Path -LiteralPath "$taskBin\manifest.json")) { $taskBin = Join-Path $taskRoot 'build\bin' }
$taskInputs = @(Get-ChildItem -LiteralPath "$taskRoot\dictionaries" -Filter 'supplement-*.json' | Sort-Object Name | ForEach-Object FullName)
& $Python -X utf8 "$taskRoot\tools\dictionary.py" --input @taskInputs --output "$taskBin\live-overlay.bin" --variants --overlay
if ($LASTEXITCODE -ne 0) { throw 'Overlay update failed' }
Write-Output 'Overlay published. With this module loaded, reopen the dialog after one second.'
