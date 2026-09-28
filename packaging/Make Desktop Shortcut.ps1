# Puts a QUIPU icon on the desktop that opens Aarav's own copy (see
# "QUIPU App.ps1"). Run it again any time to put the icon back.
#
#   powershell -ExecutionPolicy Bypass -File "packaging\Make Desktop Shortcut.ps1"

$Desktop = [Environment]::GetFolderPath("Desktop")
$Link = Join-Path $Desktop "QUIPU.lnk"
$Launcher = Join-Path $PSScriptRoot "QUIPU App.ps1"

$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($Link)
$s.TargetPath = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$s.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Launcher`""
$s.WorkingDirectory = Split-Path $PSScriptRoot -Parent
$s.IconLocation = (Join-Path $PSScriptRoot "quipu.ico") + ",0"
$s.Description = "QUIPU -- your own copy, with Autopilot"
$s.WindowStyle = 7          # minimised: the launcher's console never shows
$s.Save()
Write-Host "QUIPU is on the desktop: $Link"
