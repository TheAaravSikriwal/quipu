# Turn QUIPU's public site on and off, and whether it starts with Windows.
#
#   quipu.ps1 on          start the engine and the tunnel, in the background
#   quipu.ps1 off         stop both; the site shows "waiting for Aarav's PC"
#   quipu.ps1 status      what is running, and whether it starts at sign-in
#   quipu.ps1 auto-on     start it every time you sign in to Windows
#   quipu.ps1 auto-off    stop starting it at sign-in (does not stop it now)
#
# The .cmd files beside this do the same with a double-click.

param([Parameter(Position = 0)][ValidateSet("on", "off", "status", "auto-on", "auto-off")][string]$Do = "status")

$ErrorActionPreference = "Stop"
$Publish = Join-Path $PSScriptRoot "publish.ps1"
$Task = "QUIPU Publish"
$Port = 8848

function Procs {
    $all = Get-CimInstance Win32_Process
    $listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    $engine = @($all | Where-Object { $listen -contains $_.ProcessId })
    # uvicorn --reload serves from a child of the process that was started;
    # stopping only the child would have it respawned.
    $engine += @($all | Where-Object { $p = $_.ProcessId; $engine | Where-Object { $_.ParentProcessId -eq $p } } |
        Where-Object { $_.Name -like "python*" })
    [pscustomobject]@{
        Loop   = @($all | Where-Object { $_.Name -like "powershell*" -and $_.CommandLine -like "*publish.ps1*-Background*" })
        Tunnel = @($all | Where-Object { $_.Name -eq "cloudflared.exe" -and $_.CommandLine -like "* run quipu*" })
        Engine = $engine
    }
}

function Status {
    $p = Procs
    $auto = Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
    Write-Host ("Engine:  " + $(if ($p.Engine.Count) { "running" } else { "off" }))
    Write-Host ("Tunnel:  " + $(if ($p.Tunnel.Count) { "running -> https://quipu.wearechintu.com" } else { "off" }))
    Write-Host ("At sign-in: " + $(if ($auto -and $auto.State -ne "Disabled") { "starts automatically" } else { "does not start" }))
}

switch ($Do) {
    "on" {
        $p = Procs
        if ($p.Loop.Count -or $p.Tunnel.Count) { Write-Host "Already on."; Status; break }
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList `
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$Publish`"", "-Background"
        Write-Host "Starting..."
        $deadline = (Get-Date).AddSeconds(90)
        while (-not (Procs).Tunnel.Count -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
        Start-Sleep -Seconds 3
        Status
    }
    "off" {
        $p = Procs
        # The loop first, or it would start the tunnel again.
        foreach ($x in @($p.Loop) + @($p.Tunnel) + @($p.Engine)) {
            try { Stop-Process -Id $x.ProcessId -Force -ErrorAction Stop } catch {}
        }
        Start-Sleep -Seconds 1
        Write-Host "Off. The site now shows 'waiting for Aarav's PC'."
        Status
    }
    "status" { Status }
    "auto-on" {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument `
            "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Publish`" -Background"
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
        # Give the network a moment after sign-in; retry if it fails to start.
        $trigger.Delay = "PT30S"
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
            -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $Task -Action $action -Trigger $trigger -Settings $settings `
            -Description "Publishes QUIPU at https://quipu.wearechintu.com. Turn off with packaging\quipu.ps1 auto-off." `
            -Force | Out-Null
        Write-Host "QUIPU will start every time you sign in to Windows."
        Status
    }
    "auto-off" {
        if (Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $Task -Confirm:$false
        }
        Write-Host "QUIPU will no longer start at sign-in. (If it is on now, it stays on until 'off'.)"
        Status
    }
}
