@echo off
REM Lanza verify.py usando el Python del venv
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Venv no encontrado. Corre install.bat primero.
    pause
    exit /b 1
)

.venv\Scripts\python.exe verify.py
echo.
pause
