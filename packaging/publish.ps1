# Publish QUIPU from this PC at https://quipu.wearechintu.com
#
# Starts the engine on 127.0.0.1:8848 (unless it is already up), then runs the
# named Cloudflare Tunnel "quipu" in front of it. Ctrl+C stops the tunnel; the
# site then shows its "waiting for Aarav's PC" screen.
#
#   publish.ps1               in this window, until Ctrl+C
#   publish.ps1 -Background   no windows; the tunnel is restarted if it drops,
#                             and logs to %LOCALAPPDATA%\QUIPU\tunnel.log.
#                             This is what "QUIPU On" and the sign-in task run.
#
# One-time setup (see packaging/PUBLISH.md) must be done first:
#   cloudflared installed, logged in, tunnel "quipu" created and routed.

param([switch]$Background)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Tunnel = "quipu"
$Hostname = "quipu.wearechintu.com"
$Port = 8848
$Config = Join-Path $env:USERPROFILE ".cloudflared\config.yml"
$Logs = Join-Path $env:LOCALAPPDATA "QUIPU"
New-Item -ItemType Directory -Force $Logs | Out-Null

function Say($msg) {
    if ($Background) { Add-Content (Join-Path $Logs "publish.log") "$(Get-Date -Format s) $msg" }
    else { Write-Host $msg }
}

function Test-Engine {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch { return $false }
}

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf -and (Test-Path "C:\Program Files (x86)\cloudflared\cloudflared.exe")) {
    $cf = Get-Command "C:\Program Files (x86)\cloudflared\cloudflared.exe"
}
if (-not $cf) { Say "cloudflared is not installed. See packaging/PUBLISH.md, step 1."; exit 1 }
if (-not (Test-Path $Config)) { Say "No $Config yet. See packaging/PUBLISH.md, steps 2-4."; exit 1 }

if (Test-Engine) {
    Say "Engine already running on $Port."
} else {
    Say "Starting the engine on $Port..."
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    $style = if ($Background) { "Hidden" } else { "Minimized" }
    Start-Process -FilePath $py -ArgumentList "backend\engine.py", "--port", $Port, "--no-browser" `
        -WorkingDirectory $Root -WindowStyle $style
    $deadline = (Get-Date).AddSeconds(90)
    while (-not (Test-Engine)) {
        if ((Get-Date) -gt $deadline) { Say "Engine did not answer on $Port within 90s."; exit 1 }
        Start-Sleep -Seconds 1
    }
    Say "Engine up."
}

Say "Publishing at https://$Hostname"
if (-not $Background) {
    & $cf.Source tunnel --config $Config run $Tunnel
    exit $LASTEXITCODE
}

# In the background, a dropped tunnel (network change, sleep) is started
# again rather than leaving the site down until someone notices.
# Its own process rather than `& cloudflared`: in Windows PowerShell 5.1 a
# native program's stderr (where cloudflared logs) becomes an error record,
# and under "Stop" the first log line would end this loop.
$log = Join-Path $Logs "tunnel.log"
while ($true) {
    $p = Start-Process -FilePath $cf.Source -WindowStyle Hidden -PassThru -Wait -ArgumentList `
        "tunnel", "--config", "`"$Config`"", "--logfile", "`"$log`"", "--loglevel", "info", "run", $Tunnel
    Say "Tunnel stopped (exit $($p.ExitCode)); restarting in 10s."
    Start-Sleep -Seconds 10
}
