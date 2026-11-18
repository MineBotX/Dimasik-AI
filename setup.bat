@echo off
setlocal
cd /d "%~dp0"
title Dimasik Setup

echo ==========================================
echo          DIMASIK SETUP
echo ==========================================

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.12 was not found. Installing with winget...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo Install Python 3.12 from https://www.python.org/downloads/
    pause
    exit /b 1
  )
  winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto fail
  set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
)

py -3.12 --version
if errorlevel 1 (
  echo Python 3.12 is not available. Restart Windows and run setup again.
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
  echo Downloading Russian speech recognition model...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip' -OutFile 'vosk-model.zip'; Expand-Archive -Force 'vosk-model.zip' 'models'; Remove-Item 'vosk-model.zip'"
  if errorlevel 1 goto fail
)

where ollama >nul 2>nul
if errorlevel 1 (
  echo Installing Ollama...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo Install Ollama manually from https://ollama.com/download/windows
    pause
    exit /b 1
  )
  winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto fail
)

set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
where ollama >nul 2>nul
if errorlevel 1 (
  echo Ollama command not found. Restart Windows and run setup again.
  pause
  exit /b 1
)

echo Downloading local Qwen model. This may take a while...
ollama pull qwen2.5:3b
if errorlevel 1 goto fail

powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop'); $s=$w.CreateShortcut((Join-Path $desktop 'Dimasik.lnk')); $s.TargetPath='%CD%\.venv\Scripts\pythonw.exe'; $s.Arguments='""%CD%\assistant\main.py""'; $s.WorkingDirectory='%CD%'; $s.Save()"

echo Setup completed. Launch Dimasik from the desktop shortcut.
pause
exit /b 0

:fail
echo SETUP FAILED. Check the error above, then run setup again.
pause
exit /b 1
