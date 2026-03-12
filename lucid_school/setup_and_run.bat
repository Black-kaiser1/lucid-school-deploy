@echo off
title Lucid School Management System
color 0A

echo.
echo  ============================================================
echo    LUCID SCHOOL MANAGEMENT SYSTEM
echo    Starting up...
echo  ============================================================
echo.

:: Change to script directory first
cd /d "%~dp0"

:: ── Check Python ────────────────────────────────────────────────
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

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
echo  Python found: %PY_VER%

:: ── Install dependencies ────────────────────────────────────────
echo.
echo  Checking / installing dependencies...
python -m pip install flask reportlab pillow werkzeug --quiet --disable-pip-version-check >nul 2>&1
echo  Core packages ready.

echo  Installing desktop window support (pywebview)...
python -m pip install pywebview --quiet --disable-pip-version-check >nul 2>&1
if errorlevel 1 (
    echo  Note: pywebview unavailable - app will open in browser instead.
) else (
    echo  Desktop window support ready.
)

:: ── Create desktop shortcut (optional, silent) ──────────────────
python -c "
import os, sys, subprocess
try:
    import winreg
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    vbs_path = os.path.join(os.getcwd(), 'LucidSchool.vbs')
    lnk_path = os.path.join(desktop, 'Lucid School.lnk')
    if not os.path.exists(lnk_path):
        ps = '''$s=(New-Object -COM WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{py}';$s.Arguments='\"{app}\"';$s.WorkingDirectory='{wd}';$s.Description='Lucid School Management';$s.Save()'''.format(
            lnk=lnk_path.replace(chr(92),'\\\\'),
            py=sys.executable.replace(chr(92),'\\\\'),
            app=os.path.join(os.getcwd(),'launch_desktop.py').replace(chr(92),'\\\\'),
            wd=os.getcwd().replace(chr(92),'\\\\')
        )
        subprocess.run(['powershell','-Command',ps],capture_output=True,timeout=10)
        print('  Desktop shortcut created: Lucid School')
    else:
        print('  Desktop shortcut already exists.')
except Exception as e:
    pass
" 2>nul

:: ── Launch ──────────────────────────────────────────────────────
echo.
echo  Launching Lucid School...
echo  (A window will appear shortly. This console will close.)
echo.

:: Use python (not pythonw) via start to avoid console staying open
:: The /B flag runs without new window; we use start with minimized console
start "Lucid School" /MIN python launch_desktop.py

timeout /t 3 >nul
