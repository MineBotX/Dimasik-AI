$ErrorActionPreference = 'Stop'
$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppRoot = Join-Path $PackageRoot 'Dimasik'
if (!(Test-Path (Join-Path $AppRoot 'Dimasik.exe'))) { $AppRoot = $PackageRoot }
$Exe = Join-Path $AppRoot 'Dimasik.exe'
if (!(Test-Path $Exe)) {
    Write-Host 'Dimasik.exe was not found. Extract the entire archive first.' -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}
if (!(Test-Path (Join-Path $AppRoot 'brain\dimasik_brain.npz'))) {
    Write-Host 'The Dimasik brain files are missing. Download and extract the archive again.' -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}
$Desktop = [Environment]::GetFolderPath('Desktop')
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut((Join-Path $Desktop 'Dimasik.lnk'))
$Shortcut.TargetPath = $Exe
$Shortcut.WorkingDirectory = $AppRoot
$Shortcut.Save()
Write-Host 'Installation complete. Starting Dimasik...' -ForegroundColor Green
Start-Process -FilePath $Exe -WorkingDirectory $AppRoot
Read-Host 'Press Enter to close'
