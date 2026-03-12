@echo off
title Lucid School Management System
color 0A

echo.
echo  ==========================================
echo   LUCID SCHOOL MANAGEMENT SYSTEM
echo   Starting up...
echo  ==========================================
echo.

:: Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python is not installed or not in PATH.
    echo.
    echo  Please install Python 3.9+ from: https://www.python.org/downloads/
    echo  IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Change to the script's directory
cd /d "%~dp0"

:: Install / upgrade required packages silently
echo  Checking dependencies...
python -m pip install flask reportlab --quiet --disable-pip-version-check >nul 2>&1

:: Try to install pywebview for native window (optional but preferred)
python -m pip install pywebview --quiet --disable-pip-version-check >nul 2>&1

echo  Launching application...
echo.

:: Run the app
python run_app.py

:: If the app exits normally, pause so user can read any messages
if errorlevel 1 (
    echo.
    echo  The application encountered an error.
    pause
)
