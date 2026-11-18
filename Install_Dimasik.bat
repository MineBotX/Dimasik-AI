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
echo Downloading project from GitHub...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest '%REPO%/archive/refs/heads/main.zip' -OutFile '%ZIP%'"
if errorlevel 1 goto download_error
if not exist "%ZIP%" goto download_error
for %%A in ("%ZIP%") do if %%~zA LSS 10000 goto download_error

if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Expand-Archive -Force '%ZIP%' '%EXTRACT%'"
if errorlevel 1 goto extract_error
if not exist "%EXTRACT%\Dimasik-AI-main\setup.bat" goto extract_error

if exist "%DEST%\config.json" copy /Y "%DEST%\config.json" "%BACKUP%" >nul
if not exist "%DEST%" mkdir "%DEST%"
xcopy "%EXTRACT%\Dimasik-AI-main\*" "%DEST%\" /E /I /Y >nul
if errorlevel 1 goto copy_error

if exist "%BACKUP%" copy /Y "%BACKUP%" "%DEST%\config.json" >nul
if exist "%BACKUP%" del "%BACKUP%" >nul 2>nul
del "%ZIP%" >nul 2>nul
rmdir /s /q "%EXTRACT%" >nul 2>nul

echo Files downloaded. Starting setup...
call "%DEST%\setup.bat"
exit /b %errorlevel%

:download_error
echo ERROR: Could not download project. Check your internet connection.
pause
exit /b 1

:extract_error
echo ERROR: ZIP archive is invalid or could not be extracted.
pause
exit /b 1

:copy_error
echo ERROR: Could not copy project files.
pause
exit /b 1
