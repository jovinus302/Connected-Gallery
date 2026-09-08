param([int]$Port = 8892)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Use a port from 1024 to 65535.' }
Write-Host "Agent loop presentation: http://127.0.0.1:$Port"
Write-Host 'Keep this terminal open. Press Ctrl+C to stop.'
python -m http.server $Port --bind 127.0.0.1 --directory $PSScriptRoot
