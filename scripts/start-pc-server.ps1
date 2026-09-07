$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $project
& "$project\.venv\Scripts\python.exe" "$PSScriptRoot\start-pc-server.py"
if ($LASTEXITCODE -ne 0) { throw 'PC server startup failed' }
