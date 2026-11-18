$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppRoot = Join-Path $PackageRoot 'Dimasik'
if (!(Test-Path (Join-Path $AppRoot 'Dimasik.exe'))) { $AppRoot = $PackageRoot }
function Stop-Install([string]$Message) {
  Write-Host ""; Write-Host $Message -ForegroundColor Red
  Write-Host "Проверь интернет и свободное место, затем запусти установщик ещё раз."
  Read-Host "Нажми Enter для закрытия"; exit 1
}
Write-Host "=== Установка компонентов Димасика ===" -ForegroundColor Cyan
$OllamaExe = $null
$cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
if ($cmd) { $OllamaExe = $cmd.Source }
if (!$OllamaExe) {
  $candidates = @((Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),(Join-Path $env:ProgramFiles 'Ollama\ollama.exe'))
  $OllamaExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (!$OllamaExe) {
  if (!(Get-Command winget.exe -ErrorAction SilentlyContinue)) { Stop-Install "Не найден winget. Установи Ollama вручную: https://ollama.com/download/windows" }
  Write-Host "Устанавливаю Ollama..." -ForegroundColor Yellow
  & winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) { Stop-Install "Не удалось установить Ollama через winget." }
  $cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
  if ($cmd) { $OllamaExe = $cmd.Source }
  if (!$OllamaExe) {
    $candidates = @((Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),(Join-Path $env:ProgramFiles 'Ollama\ollama.exe'))
    $OllamaExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  }
}
if (!$OllamaExe) { Stop-Install "Ollama установлена, но файл не найден. Перезагрузи Windows и повтори." }
Write-Host "Проверяю локальный сервер Ollama..." -ForegroundColor Yellow
$ready = $false
try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 | Out-Null; $ready = $true } catch {}
if (!$ready) {
  Start-Process -FilePath $OllamaExe -ArgumentList 'serve' -WindowStyle Hidden
  for ($i=0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 | Out-Null; $ready = $true; break } catch {}
  }
}
if (!$ready) { Stop-Install "Ollama не запустилась. Открой её из меню Пуск и повтори установку." }
$installed = $false
try { $tags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 10; $installed = @($tags.models | ForEach-Object { $_.name }) -contains 'qwen2.5:3b' } catch {}
if (!$installed) {
  Write-Host "Скачиваю Qwen 2.5 3B. Загрузка может занять время и несколько гигабайт диска..." -ForegroundColor Yellow
  & $OllamaExe pull qwen2.5:3b
  if ($LASTEXITCODE -ne 0) { Stop-Install "Не удалось скачать Qwen 2.5 3B." }
}
try {
  $tags = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 10
  if (@($tags.models | ForEach-Object { $_.name }) -notcontains 'qwen2.5:3b') { Stop-Install "Проверка не нашла Qwen после загрузки." }
} catch { Stop-Install "Не удалось проверить модель Qwen: $($_.Exception.Message)" }
if (!(Test-Path (Join-Path $AppRoot 'Dimasik.exe'))) { Stop-Install "Не найден Dimasik.exe. Распакуй весь архив и запускай этот BAT из его папки." }
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $desktop 'Димасик.lnk'))
$link.TargetPath = Join-Path $AppRoot 'Dimasik.exe'
$link.WorkingDirectory = $AppRoot
$link.Save()
Write-Host ""; Write-Host "Готово! Ollama и Qwen установлены, ярлык создан." -ForegroundColor Green
Start-Process -FilePath (Join-Path $AppRoot 'Dimasik.exe') -WorkingDirectory $AppRoot
Read-Host "Нажми Enter для закрытия"
exit 0
