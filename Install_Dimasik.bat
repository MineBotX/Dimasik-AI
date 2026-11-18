@echo off
setlocal
title Dimasik Installer
set "REPO=https://github.com/MineBotX/Dimasik-AI"
set "ZIP=%TEMP%\Dimasik-AI-main.zip"
set "EXTRACT=%TEMP%\Dimasik-AI-extract"
set "DEST=%LOCALAPPDATA%\Dimasik"
set "BACKUP=%TEMP%\Dimasik-config-backup.json"

echo ==========================================
echo          DIMASIK INSTALLER
echo ==========================================
echo Downloading the latest version from GitHub...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest '%REPO%/archive/refs/heads/main.zip' -OutFile '%ZIP%'"
if errorlevel 1 goto download_error
if not exist "%ZIP%" goto download_error
for %%A in ("%ZIP%") do if %%~zA LSS 10000 goto download_error

if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%EXTRACT%' -Force"
if errorlevel 1 goto extract_error
if not exist "%EXTRACT%\Dimasik-AI-main\setup.ps1" goto extract_error

if exist "%DEST%\config.json" copy /Y "%DEST%\config.json" "%BACKUP%" >nul
if not exist "%DEST%" mkdir "%DEST%"
robocopy "%EXTRACT%\Dimasik-AI-main" "%DEST%" /E /XD .git .venv models /XF *.pyc >nul
if errorlevel 8 goto copy_error

if exist "%BACKUP%" copy /Y "%BACKUP%" "%DEST%\config.json" >nul
if exist "%BACKUP%" del "%BACKUP%" >nul 2>nul
del "%ZIP%" >nul 2>nul
rmdir /s /q "%EXTRACT%" >nul 2>nul

echo Download complete. Starting setup...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%DEST%\setup.ps1"
if errorlevel 1 goto setup_error
exit /b 0

:download_error
echo ERROR: Download failed. Check your internet connection.
pause
exit /b 1
:extract_error
echo ERROR: ZIP archive is invalid or missing setup.ps1.
pause
exit /b 1
:copy_error
echo ERROR: Could not copy project files.
pause
exit /b 1
:setup_error
echo Setup did not finish. Read the error above and run this installer again.
pause
exit /b 1
