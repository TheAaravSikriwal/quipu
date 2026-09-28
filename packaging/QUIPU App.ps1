# Opens Aarav's own QUIPU -- the copy with Autopilot and the Alpaca account --
# in a window of its own, from the desktop icon. No address bar, no typing
# localhost: this computer's engine is the only place the owner's controls
# exist, and the public address never shows them to anyone.
#
# Starts the engine first if it is not already answering (it normally is:
# it starts at sign-in), then opens it as a Chrome app window, or Edge's if
# there is no Chrome, or the default browser as a last resort.
#
# The desktop shortcut is made by "Make Desktop Shortcut.ps1" beside this.

$ErrorActionPreference = "SilentlyContinue"
$Port = 8848
$Root = Split-Path $PSScriptRoot -Parent
$Url = "http://localhost:$Port/"

function Up {
    try { (Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 }
    catch { $false }
}

if (-not (Up)) {
    # The usual way: engine and tunnel together, as at sign-in.
    & (Join-Path $PSScriptRoot "quipu.ps1") on | Out-Null
    $deadline = (Get-Date).AddSeconds(45)
    while (-not (Up) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
}
if (-not (Up)) {
    # The tunnel was up but the engine was not: start the engine alone.
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    Start-Process -FilePath $py -ArgumentList "backend\engine.py", "--port", $Port, "--no-browser" `
        -WorkingDirectory $Root -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(45)
    while (-not (Up) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
}

$browsers = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
)
$app = $browsers | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($app) {
    Start-Process -FilePath $app -ArgumentList "--app=$Url", "--window-size=1680,1000"
} else {
    Start-Process $Url
}
