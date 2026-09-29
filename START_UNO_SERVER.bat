@echo off
title UNO Game Server
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Python was not found on this PC.
  echo   Install it from https://python.org and tick "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

python host_game.py %*

echo.
pause
