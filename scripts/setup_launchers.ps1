# One-time (or re-run anytime) setup: creates the DB.Whisperer Desktop
# shortcut, the Start Menu entry, and a Start Menu utility that recreates the
# Desktop shortcut on demand (for when it gets deleted, or the repo moves).
#
# Run manually: powershell -ExecutionPolicy Bypass -File scripts\setup_launchers.ps1

$root = Split-Path $PSScriptRoot -Parent
$exePath = Join-Path $root "dist\DB.Whisperer\DB.Whisperer.exe"
$iconPath = Join-Path $root "assets\app_icon.ico"
$workDir = Join-Path $root "dist\DB.Whisperer"
$startMenuPrograms = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"

if (-not (Test-Path $exePath)) {
    Write-Host "DB.Whisperer.exe not found at $exePath -- build it first (pyinstaller db_whisperer.spec)." -ForegroundColor Red
    exit 1
}

$shell = New-Object -ComObject WScript.Shell

function New-AppShortcut([string]$lnkPath) {
    $s = $shell.CreateShortcut($lnkPath)
    $s.TargetPath = $exePath
    $s.WorkingDirectory = $workDir
    if (Test-Path $iconPath) { $s.IconLocation = "$iconPath,0" }
    $s.Description = "DB.Whisperer -- natural language to SQL"
    $s.Save()
    Write-Host "Created: $lnkPath"
}

# 1. Desktop launcher
New-AppShortcut "$env:USERPROFILE\Desktop\DB.Whisperer.lnk"

# 2. Start Menu launcher
New-AppShortcut "$startMenuPrograms\DB.Whisperer.lnk"

# 3. Start Menu utility: re-creates the Desktop shortcut on demand, in case it
#    gets deleted or the project folder moves. Runs create_desktop_shortcut.ps1
#    through powershell.exe rather than being that script itself, so the two
#    stay independently runnable (double-click from Start Menu, or from a
#    terminal without going through a shortcut at all).
$utilityLnk = "$startMenuPrograms\Create DB.Whisperer Desktop Shortcut.lnk"
$utilityScript = Join-Path $PSScriptRoot "create_desktop_shortcut.ps1"
$utility = $shell.CreateShortcut($utilityLnk)
$utility.TargetPath = "powershell.exe"
$utility.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$utilityScript`""
if (Test-Path $iconPath) { $utility.IconLocation = "$iconPath,0" }
$utility.Description = "Recreates the DB.Whisperer Desktop shortcut"
$utility.Save()
Write-Host "Created: $utilityLnk"
