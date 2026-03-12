@echo off
title Lucid School — Build Standalone EXE
color 0B
echo.
echo  ============================================================
echo    Building Lucid School as a Standalone .exe
echo    This may take 2-5 minutes. Please wait...
echo  ============================================================
echo.

:: Install PyInstaller
python -m pip install pyinstaller pywebview --quiet

:: Build
pyinstaller ^
  --name "LucidSchool" ^
  --onefile ^
  --windowed ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --add-data "instance;instance" ^
  --hidden-import flask ^
  --hidden-import reportlab ^
  --hidden-import PIL ^
  --hidden-import webview ^
  --hidden-import engineio ^
  --hidden-import jinja2 ^
  --hidden-import werkzeug ^
  launch_desktop.py

if errorlevel 1 (
    echo.
    echo  BUILD FAILED. Check errors above.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo    BUILD COMPLETE!
echo    Your standalone exe is at:
echo      dist\LucidSchool.exe
echo.
echo    Copy the entire "dist\LucidSchool" folder OR just
echo    LucidSchool.exe to any Windows PC.
echo    (The instance\ folder with the database will be created
echo     automatically on first run.)
echo  ============================================================
echo.
pause
