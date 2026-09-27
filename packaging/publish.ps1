# Publish QUIPU from this PC at https://quipu.wearechintu.com
#
# Starts the engine on 127.0.0.1:8848 (unless it is already up), then runs the
# named Cloudflare Tunnel "quipu" in front of it. Ctrl+C stops the tunnel; the
# site then shows its "waiting for Aarav's PC" screen.
#
# One-time setup (see packaging/PUBLISH.md) must be done first:
#   cloudflared installed, logged in, tunnel "quipu" created and routed.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Tunnel = "quipu"
$Hostname = "quipu.wearechintu.com"
$Port = 8848
$Config = Join-Path $env:USERPROFILE ".cloudflared\config.yml"

function Test-Engine {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch { return $false }
}

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    Write-Host "cloudflared is not installed. See packaging/PUBLISH.md, step 1." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Config)) {
    Write-Host "No $Config yet. See packaging/PUBLISH.md, steps 2-4." -ForegroundColor Red
    exit 1
}

if (Test-Engine) {
    Write-Host "Engine already running on $Port."
} else {
    Write-Host "Starting the engine on $Port..."
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    Start-Process -FilePath $py -ArgumentList "backend\engine.py", "--port", $Port, "--no-browser" `
        -WorkingDirectory $Root -WindowStyle Minimized
    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-Engine)) {
        if ((Get-Date) -gt $deadline) {
            Write-Host "Engine did not answer on $Port within 60s." -ForegroundColor Red
            exit 1
        }
        Start-Sleep -Seconds 1
    }
    Write-Host "Engine up."
}

Write-Host "Publishing at https://$Hostname (Ctrl+C to stop)..."
& $cf.Source tunnel --config $Config run $Tunnel
