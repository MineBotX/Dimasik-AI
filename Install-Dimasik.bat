@echo off
setlocal
title Установка Димасика
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-runtime.ps1"
if errorlevel 1 (
  echo.
  pause
)
