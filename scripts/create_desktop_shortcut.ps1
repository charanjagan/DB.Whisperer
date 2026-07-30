# Creates/refreshes the DB.Whisperer Desktop shortcut on demand. Meant to be
# launched by double-clicking "Create DB.Whisperer Desktop Shortcut" in the
# Start Menu -- see setup_launchers.ps1, which creates that entry -- not run
# as part of any build or app-launch path.

$root = Split-Path $PSScriptRoot -Parent
$exePath = Join-Path $root "dist\DB.Whisperer\DB.Whisperer.exe"
$iconPath = Join-Path $root "assets\app_icon.ico"

if (-not (Test-Path $exePath)) {
    Write-Host "DB.Whisperer.exe not found at $exePath -- build it first (pyinstaller db_whisperer.spec)." -ForegroundColor Red
    Start-Sleep -Seconds 4
    exit 1
}

$lnkPath = "$env:USERPROFILE\Desktop\DB.Whisperer.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnkPath)
$shortcut.TargetPath = $exePath
$shortcut.WorkingDirectory = Split-Path $exePath -Parent
if (Test-Path $iconPath) {
    $shortcut.IconLocation = "$iconPath,0"
}
$shortcut.Description = "DB.Whisperer -- natural language to SQL"
$shortcut.Save()

Write-Host "Desktop shortcut created: $lnkPath"
Start-Sleep -Seconds 3
