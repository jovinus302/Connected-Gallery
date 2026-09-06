$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $project
# Optional GPU wheels are isolated from the tested CPU environment.
$cudaPackages = Join-Path $project '.runtime\torch-cuda'
if (Test-Path -LiteralPath (Join-Path $cudaPackages 'torch\__init__.py')) {
    $env:PYTHONPATH = if ($env:PYTHONPATH) { "$cudaPackages;$env:PYTHONPATH" } else { $cudaPackages }
}
& "$project\.venv\Scripts\python.exe" -m uvicorn connected_gallery.bootstrap.api:create_app --factory --host 127.0.0.1 --port 8765
