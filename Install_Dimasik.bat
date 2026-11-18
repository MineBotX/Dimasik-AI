@echo off
setlocal
title Установщик Димасика
set "REPO=https://github.com/MineBotX/Dimasik-AI"
set "ZIP=%TEMP%\Dimasik-AI-main.zip"
set "EXTRACT=%TEMP%\Dimasik-AI-extract"
set "DEST=%LOCALAPPDATA%\Dimasik"

echo ==========================================
echo       УСТАНОВКА ГОЛОСОВОГО ДИМАСИКА
echo ==========================================
echo Скачиваю последнюю версию с GitHub...

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest '%REPO%/archive/refs/heads/main.zip' -OutFile '%ZIP%'"
if errorlevel 1 (
  echo Не удалось скачать проект. Проверь подключение к интернету.
  pause
  exit /b 1
)

if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force '%ZIP%' '%EXTRACT%'"
if errorlevel 1 goto fail

if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%DEST%"
xcopy "%EXTRACT%\Dimasik-AI-main\*" "%DEST%\" /E /I /Y >nul
if errorlevel 1 goto fail

del "%ZIP%" >nul 2>nul
rmdir /s /q "%EXTRACT%" >nul 2>nul

call "%DEST%\setup.bat"
exit /b %errorlevel%

:fail
echo Ошибка скачивания или распаковки.
pause
exit /b 1
