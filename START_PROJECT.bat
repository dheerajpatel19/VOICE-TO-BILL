@echo off
title Voice to Bill - Grocery Shop Management
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed or is not added to PATH.
  echo Install Python 3 and select "Add Python to PATH".
  pause
  exit /b 1
)
start "" http://localhost:8000
python app.py
pause
