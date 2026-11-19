$ErrorActionPreference = 'Stop'
$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppRoot = Join-Path $PackageRoot 'Dimasik'
if (!(Test-Path (Join-Path $AppRoot 'Dimasik.exe'))) { $AppRoot = $PackageRoot }
$Exe = Join-Path $AppRoot 'Dimasik.exe'
if (!(Test-Path $Exe)) { Write-Host "Не найден Dimasik.exe. Распакуй архив полностью." -ForegroundColor Red; Read-Host "Enter"; exit 1 }
if (!(Test-Path (Join-Path $AppRoot 'brain\dimasik_brain.npz'))) { Write-Host "Не найдены файлы собственного ядра Димасика. Скачай архив заново." -ForegroundColor Red; Read-Host "Enter"; exit 1 }
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $desktop 'Димасик.lnk'))
$link.TargetPath = $Exe
$link.WorkingDirectory = $AppRoot
$link.Save()
Write-Host "Готово! Димасик установлен. Qwen и Ollama не используются." -ForegroundColor Green
Start-Process -FilePath $Exe -WorkingDirectory $AppRoot
Read-Host "Нажми Enter для закрытия"
