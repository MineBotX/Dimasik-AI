@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Настройка Димасика

echo ==========================================
echo          НАСТРОЙКА ДИМАСИКА
echo ==========================================

where py >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Устанавливаю Python 3.12 через winget...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo Не найден winget. Установи Python 3.12: https://www.python.org/downloads/
    pause
    exit /b 1
  )
  winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto fail
  set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
)

py -3.12 --version
if errorlevel 1 (
  echo Python 3.12 не найден в PATH. Перезапусти установщик после установки Python.
  pause
  exit /b 1
)

if not exist .venv py -3.12 -m venv .venv
if errorlevel 1 goto fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto fail
pip install -r requirements.txt
if errorlevel 1 goto fail

if not exist models mkdir models
if not exist models\vosk-model-small-ru-0.22 (
  echo Загружаю русскую модель распознавания речи...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip' -OutFile 'vosk-model.zip'; Expand-Archive -Force 'vosk-model.zip' 'models'; Remove-Item 'vosk-model.zip'"
  if errorlevel 1 goto fail
)

where ollama >nul 2>nul
if errorlevel 1 (
  echo Устанавливаю Ollama...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo Установи Ollama вручную: https://ollama.com/download/windows
    pause
    exit /b 1
  )
  winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto fail
)
set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
where ollama >nul 2>nul
if errorlevel 1 (
  echo Ollama установлена, но команда пока недоступна.
  echo Перезапусти Windows и запусти setup.bat снова.
  pause
  exit /b 1
)

echo Загружаю локальную модель Qwen 2.5 3B. Это может занять время...
ollama pull qwen2.5:3b
if errorlevel 1 (
  echo Не удалось загрузить ИИ-модель. Повтори позже команду: ollama pull qwen2.5:3b
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop'); $s=$w.CreateShortcut((Join-Path $desktop 'Димасик.lnk')); $s.TargetPath='%CD%\.venv\Scripts\python.exe'; $s.Arguments='""%CD%\assistant\main.py""'; $s.WorkingDirectory='%CD%'; $s.Save()"

echo.
echo Установка завершена! Запусти ярлык Димасик на рабочем столе.
pause
exit /b 0

:fail
echo.
echo ОШИБКА УСТАНОВКИ. Проверь интернет и попробуй запустить setup.bat снова.
pause
exit /b 1
