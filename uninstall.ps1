$Desktop = [System.Environment]::GetFolderPath('Desktop')
$StartMenu = [System.Environment]::GetFolderPath('Programs')

$DesktopShortcut = Join-Path $Desktop "FinCom Books.lnk"
if (Test-Path $DesktopShortcut) { Remove-Item -Path $DesktopShortcut -Force }

$AppStartMenu = Join-Path $StartMenu "FinCom Books"
if (Test-Path $AppStartMenu) { Remove-Item -Path $AppStartMenu -Recurse -Force }

Write-Host "Shortcuts removed. To complete removal, delete directory: $PSScriptRoot" -ForegroundColor Yellow
