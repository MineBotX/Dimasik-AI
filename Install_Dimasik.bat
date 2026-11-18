@echo off
chcp 65001 >nul
setlocal
title Установщик Димасика
set "REPO=https://github.com/MineBotX/Dimasik-AI"
set "ZIP=%TEMP%\Dimasik-AI-main.zip"
set "EXTRACT=%TEMP%\Dimasik-AI-extract"
set "DEST=%LOCALAPPDATA%\Dimasik"
set "SAVED_CONFIG=%TEMP%\Dimasik-config-backup.json"

echo ==========================================
echo       УСТАНОВКА ГОЛОСОВОГО ДИМАСИКА
echo ==========================================
echo Скачиваю проект с GitHub...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest '%REPO%/archive/refs/heads/main.zip' -OutFile '%ZIP%'"
if errorlevel 1 goto download_error
if not exist "%ZIP%" goto download_error
for %%A in ("%ZIP%") do if %%~zA LSS 10000 goto download_error

if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Expand-Archive -Force '%ZIP%' '%EXTRACT%'"
if errorlevel 1 goto extract_error
if not exist "%EXTRACT%\Dimasik-AI-main\setup.bat" goto extract_error

if exist "%DEST%\config.json" copy /Y "%DEST%\config.json" "%SAVED_CONFIG%" >nul
if not exist "%DEST%" mkdir "%DEST%"
xcopy "%EXTRACT%\Dimasik-AI-main\*" "%DEST%\" /E /I /Y >nul
if errorlevel 1 goto copy_error
if exist "%SAVED_CONFIG%" (
  copy /Y "%SAVED_CONFIG%" "%DEST%\config.json" >nul
  del "%SAVED_CONFIG%" >nul 2>nul
)

del "%ZIP%" >nul 2>nul
rmdir /s /q "%EXTRACT%" >nul 2>nul
call "%DEST%\setup.bat"
exit /b %errorlevel%

:download_error
echo.
echo ОШИБКА: не удалось скачать архив с GitHub. Проверь интернет.
pause
exit /b 1
:extract_error
echo.
echo ОШИБКА: архив поврежден или не распаковался.
pause
exit /b 1
:copy_error
echo.
echo ОШИБКА: не удалось скопировать файлы проекта.
pause
exit /b 1
