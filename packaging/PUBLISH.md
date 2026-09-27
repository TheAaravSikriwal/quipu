# Publishing QUIPU from this PC

QUIPU is served at **https://quipu.wearechintu.com** by a named Cloudflare
Tunnel that runs on this computer and forwards to the engine on
`127.0.0.1:8848`. The engine never listens on the network; the tunnel makes
an outbound connection to Cloudflare, so no router ports are opened.

`wearechintu.com/quipu` frames that address. When the tunnel is down, the
page shows "waiting for Aarav's PC".

## One-time setup

Run these in PowerShell. Steps 2 and 3 open a browser to sign in to Cloudflare,
so they need you.

1. **Install cloudflared**

   ```powershell
   winget install --id Cloudflare.cloudflared
   ```

   Open a new terminal afterwards so `cloudflared` is on PATH.

2. **Log in.** Pick the `wearechintu.com` zone when the browser asks. This
   writes `%USERPROFILE%\.cloudflared\cert.pem`.

   ```powershell
   cloudflared tunnel login
   ```

3. **Create the tunnel and point the hostname at it**

   ```powershell
   cloudflared tunnel create quipu
   cloudflared tunnel route dns quipu quipu.wearechintu.com
   ```

   `create` prints the tunnel's ID and writes
   `%USERPROFILE%\.cloudflared\<ID>.json`, which holds the tunnel's secret.
   Keep that file private: never commit it or copy it under OneDrive.

4. **Write the config** to `%USERPROFILE%\.cloudflared\config.yml`, with
   `<ID>` replaced by the ID from step 3:

   ```yaml
   tunnel: quipu
   credentials-file: C:\Users\Aarav\.cloudflared\<ID>.json

   ingress:
     - hostname: quipu.wearechintu.com
       service: http://127.0.0.1:8848
     - service: http_status:404
   ```

## Every time

```powershell
powershell -ExecutionPolicy Bypass -File packaging\publish.ps1
```

This starts the engine if it isn't running, then runs the tunnel. Ctrl+C
stops publishing; the engine keeps running locally.

## What visitors can and can't do

Every request through the tunnel carries `CF-Connecting-IP`. The engine
(`backend/share.py`) uses that header to share cached answers between
visitors, apply fair-use limits per visitor, and queue heavy jobs. Only
requests from this PC itself can use the Alpaca switch or the 10,000-stock
rescan.

## Turning it off for good

```powershell
cloudflared tunnel delete quipu
```

Then delete the `quipu` CNAME in the Cloudflare DNS dashboard.
