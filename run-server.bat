@echo off
REM ================================================================
REM  Tableau Workflow Assistant - MCP Server Runner
REM
REM  Lanza server.py usando el Python del venv.
REM  Claude Desktop invocara este .bat (no python.exe directo) para
REM  no depender del PATH global del sistema.
REM
REM  Las variables del .env las carga server.py via python-dotenv.
REM  No las parseamos aca (el parser previo era frágil con valores que
REM  contenian '=' o whitespace).
REM ================================================================

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Venv no encontrado. Corre install.bat primero.
    exit /b 1
)

if not exist ".env" (
    echo [ERROR] .env no existe. Copia .env.example a .env y completalo.
    exit /b 1
)

.venv\Scripts\python.exe server.py
