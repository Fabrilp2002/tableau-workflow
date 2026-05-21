# =================================================================
# install-mcp-claude.ps1
# Agrega (o actualiza) la entrada "tableau-workflow" en
# %APPDATA%\Claude\claude_desktop_config.json sin pisar otros MCPs.
#
# Uso:
#   Click derecho sobre este archivo en el Explorador -> "Run with PowerShell"
#   o desde una ventana PowerShell:  .\install-mcp-claude.ps1
# =================================================================

$ErrorActionPreference = "Stop"

# Detect project root (parent of this script)
$projectRoot = Split-Path $MyInvocation.MyCommand.Path -Parent
$configPath  = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
$serverBat   = Join-Path $projectRoot "run-server.bat"

Write-Host ""
Write-Host "=== Registrar tableau-workflow MCP en Claude Desktop ===" -ForegroundColor Cyan
Write-Host "Config destino: $configPath"
Write-Host "Server bat:     $serverBat"
Write-Host ""

# Verificar que run-server.bat existe
if (-not (Test-Path $serverBat)) {
    Write-Host "[ERROR] No encuentro run-server.bat en $serverBat" -ForegroundColor Red
    Write-Host "Make sure run-server.bat exists next to this script." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Asegurarse que la carpeta de Claude existe
$claudeDir = Split-Path $configPath -Parent
if (-not (Test-Path $claudeDir)) {
    Write-Host "[INFO] La carpeta $claudeDir no existe - la creo."
    New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null
}

# Leer config existente (o empezar uno nuevo)
if (Test-Path $configPath) {
    Write-Host "[INFO] Config existente detectada - la voy a actualizar sin pisar otros MCPs."

    # Backup antes de tocar
    $backupPath = "$configPath.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item $configPath $backupPath
    Write-Host "[OK]   Backup en: $backupPath"

    try {
        $config = Get-Content $configPath -Raw | ConvertFrom-Json
    } catch {
        Write-Host "[ERROR] No pude parsear el JSON existente: $_" -ForegroundColor Red
        Write-Host "Mira el archivo a mano y arreglalo, o borralo para empezar de cero." -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }

    if (-not $config.mcpServers) {
        # No tenia mcpServers - lo agrego
        $config | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{}) -Force
    }
} else {
    Write-Host "[INFO] No habia config - la creo desde cero."
    $config = [pscustomobject]@{
        mcpServers = [pscustomobject]@{}
    }
}

# Agregar / actualizar entrada
$entry = [pscustomobject]@{
    command = $serverBat
    args    = @()
}

$config.mcpServers | Add-Member -NotePropertyName "tableau-workflow" -NotePropertyValue $entry -Force

# Guardar (sin BOM para que sea JSON valido para todos los parsers)
$json = $config | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($configPath, $json, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "[OK]   $configPath actualizado." -ForegroundColor Green
Write-Host ""
Write-Host "--- Contenido final ---"
Get-Content $configPath
Write-Host ""
Write-Host "Siguiente paso: cerrar y reabrir Claude Desktop completamente."
Write-Host "(Boton derecho en el icono de la bandeja del sistema -> Quit, despues reabrir.)"
Write-Host ""
Read-Host "Press Enter to exit"
