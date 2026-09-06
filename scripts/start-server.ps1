$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $project
& "$project\.venv\Scripts\python.exe" -m uvicorn connected_gallery.bootstrap.api:create_app --factory --host 127.0.0.1 --port 8765
