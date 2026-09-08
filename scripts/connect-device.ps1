$ErrorActionPreference = 'Stop'
$androidSdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
& "$PSScriptRoot\..\.venv\Scripts\python.exe" "$PSScriptRoot\install-device.py" --adb "$androidSdk\platform-tools\adb.exe"
if ($LASTEXITCODE -ne 0) { throw 'APK installation failed' }
& "$PSScriptRoot\..\.venv\Scripts\python.exe" "$PSScriptRoot\configure-device.py"
if ($LASTEXITCODE -ne 0) { throw 'Device configuration failed' }
