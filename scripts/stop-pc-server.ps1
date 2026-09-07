$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$network = Join-Path $project '.runtime\network'
$tunnelRecord = Join-Path $network 'tunnel-process.json'
if (Test-Path -LiteralPath $tunnelRecord) {
    $record = Get-Content -LiteralPath $tunnelRecord -Raw | ConvertFrom-Json
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.pid)"
    $expected = Join-Path $project '.runtime\bin\cloudflared.exe'
    if ($process -and $process.ExecutablePath -eq $expected -and $process.CommandLine -like '*http://127.0.0.1:8765*') {
        Stop-Process -Id $process.ProcessId
    } elseif ($process) { throw 'Tunnel PID belongs to an unexpected process; left untouched' }
}
$serverRecord = Join-Path $network 'server-process.json'
if (Test-Path -LiteralPath $serverRecord) {
    $record = Get-Content -LiteralPath $serverRecord -Raw | ConvertFrom-Json
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.pid)"
    if ($process -and $process.CommandLine -like '*uvicorn connected_gallery.bootstrap.api:create_app*') {
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($process.ProcessId)"
        foreach ($child in $children) {
            if ($child.CommandLine -like '*uvicorn connected_gallery.bootstrap.api:create_app*') { Stop-Process -Id $child.ProcessId }
        }
        Stop-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
    } elseif ($process) { throw 'Server PID belongs to an unexpected process; left untouched' }
}
Write-Output 'Managed PC server and tunnel stopped.'
