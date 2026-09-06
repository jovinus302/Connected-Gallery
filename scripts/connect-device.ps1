$ErrorActionPreference = 'Stop'
$androidSdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
& "$androidSdk\platform-tools\adb.exe" reverse tcp:8765 tcp:8765
& "$androidSdk\platform-tools\adb.exe" install -r "$PSScriptRoot\..\android\app\build\outputs\apk\debug\app-debug.apk"
