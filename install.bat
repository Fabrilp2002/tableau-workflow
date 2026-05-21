@echo off
REM ================================================================
REM  Tableau Workflow Assistant - Installer (Windows)
REM
REM  Crea un venv local, instala las dependencias, y prepara .env
REM  desde .env.example si no existe.
REM
REM  Uso:  doble-click sobre este archivo, o desde cmd:
REM        cd C:\path\to\tableau-workflow
REM        install.bat
REM ================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo === Tableau Workflow Assistant - Install ===
echo Carpeta: %CD%
echo.

REM --- 1) Chequear Python ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python no esta en PATH. Instala Python 3.10+ desde https://www.python.org/downloads/
    echo         Durante la instalacion, marca "Add Python to PATH".
    pause
    exit /b 1
)

for /f "tokens=2" %%I in ('python --version 2^>^&1') do set PYVER=%%I
echo [OK] Python detectado: !PYVER!

REM --- 2) Crear venv si no existe ---
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creando entorno virtual .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No pude crear el venv.
        pause
        exit /b 1
    )
) else (
    echo [OK] Venv ya existe.
)

REM --- 3) Activar venv e instalar deps ---
echo [INFO] Instalando dependencias en el venv ...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Fallo el pip install. Revisa requirements.txt y tu conexion.
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas.

REM --- 4) Crear .env si no existe ---
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [INFO] Cree .env desde .env.example. Editalo con tu PAT y URL antes de correr el server.
    echo        Path: %CD%\.env
) else (
    echo [OK] .env ya existe (no lo toque).
)

echo.
echo === Setup terminado ===
echo Siguiente paso: editar .env con tu TABLEAU_PAT_VALUE y correr verify.bat
echo.
pause
