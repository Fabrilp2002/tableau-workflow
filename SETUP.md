# Tableau Workflow Assistant — Setup (Windows + Claude Desktop)

Step-by-step guide to install and run the MCP server + the Skill on your machine with Claude Desktop. Paths use the placeholder `C:\path\to\tableau-workflow\` — replace it with the location where you cloned this repo.

> **Note on OneDrive / cloud-synced folders**: your `.env` contains a PAT (secret). If the project lives inside OneDrive/Dropbox/etc, your PAT ends up synced to that provider's cloud. Recommended: clone the repo to a non-synced folder like `C:\Users\<you>\tableau-workflow\`.
>
> **Seguridad**: para detalles del threat model, postura de seguridad, auditoría y recomendaciones de operación segura, ver [`SECURITY.md`](./SECURITY.md). Resumen: auditoría hecha, 1 HIGH y 3 MEDIUM fixeados (zip slip, GraphQL injection, path traversal, confirm en backup), PAT bien manejado.

---

## Resumen de pasos

1. Instalar Python 3.10+ (si no lo tenés)
2. Generar el PAT en Tableau Cloud
3. Correr `install.bat` (crea venv + instala deps + arma `.env`)
4. Editar `.env` con tu PAT real
5. Correr `verify.bat` (smoke test contra Tableau Cloud)
6. Registrar el MCP en `claude_desktop_config.json`
7. Instalar la Skill en Claude Desktop
8. Reiniciar Claude Desktop
9. Smoke test desde Claude: pedirle un `site_info` y un refresh

---

## 1. Python 3.10+

Abrí `cmd` y escribí:

```cmd
python --version
```

Si dice 3.10 o superior, listo. Si no aparece o es viejo, instalá desde https://www.python.org/downloads/ — durante el wizard tildá **"Add Python to PATH"**.

---

## 2. Personal Access Token (PAT) de Tableau Cloud

1. Abrí Tableau Cloud en el browser (`https://prod-useast-a.online.tableau.com`).
2. Click en tu avatar (esquina superior derecha) → **My Account Settings**.
3. Bajá hasta **Personal Access Tokens**.
4. **Create new token** con nombre `mcp-workflow` (o el que quieras — anotalo).
5. Tableau te muestra el **secret una sola vez**. Copialo ahora.
6. Si dejás de usarlo más de 15 días, expira — tendrás que regenerarlo.

---

## 3. Correr `install.bat`

Doble-click sobre `install.bat` (o desde `cmd`: `cd C:\path\to\tableau-workflow && install.bat`).

Qué hace:
- Crea `.venv\` con un entorno Python aislado.
- Instala las 3 dependencias (`mcp`, `tableauserverclient`, `python-dotenv`).
- Copia `.env.example` → `.env` si todavía no existe.

Al final tenés que ver `=== Setup terminado ===`.

---

## 4. Editar `.env`

Abrí `C:\path\to\tableau-workflow\.env` con Notepad o cualquier editor. Llenalo así:

```ini
TABLEAU_SERVER_URL=https://prod-useast-a.online.tableau.com
TABLEAU_SITE_NAME=your-site-slug
TABLEAU_PAT_NAME=mcp-workflow
TABLEAU_PAT_VALUE=pega-aqui-el-secret-de-tu-PAT

# Carpeta con tus .twb/.twbx locales (sin comillas):
TABLEAU_LOCAL_FOLDER=C:/Users/<you>/Documents/Tableau

# Dónde guardar el índice del catálogo (default OK):
TABLEAU_CATALOG_PATH=
```

> Importante: usá barras `/` en los paths o barras dobles `\\`, no barras simples `\` (Python las interpreta como escape).

---

## 5. Verificar la instalación

Doble-click sobre `verify.bat`. Esto corre `verify.py`, que:
- chequea Python, deps y `.env`
- consulta `site_info` contra Tableau Cloud (valida el PAT)
- lista proyectos / workbooks / datasources

Salida esperada al final:

```
[OK]  Conectividad a Tableau Cloud
      product_version: 2025.x
      rest_api:        3.xx
      site_id:         xxxxxxxx-xxxx-xxxx
[OK]  Listing OK
      projects:    N
      workbooks:   M
      datasources: K

============================================================
 Todo OK — el MCP está listo para conectarse a Claude Desktop.
============================================================
```

Si algo falla, el mensaje `[FAIL]` te dice qué chequear (PAT expirado, server URL, etc.).

---

## 6. Registrar el MCP en Claude Desktop

Abrí (creá si no existe) el archivo:

```
%APPDATA%\Claude\claude_desktop_config.json
```

Atajo: en el Explorador, pegá `%APPDATA%\Claude\` en la barra de direcciones.

### Caso A — el archivo está vacío o no existe

Crealo con este contenido:

```json
{
  "mcpServers": {
    "tableau-workflow": {
      "command": "C:\\path\\to\\tableau-workflow\\run-server.bat",
      "args": []
    }
  }
}
```

### Caso B — ya tenés otros MCP servers configurados

Solo agregá la entrada `"tableau-workflow"` dentro del bloque `"mcpServers"` existente. Ejemplo:

```json
{
  "mcpServers": {
    "algun-otro-mcp": { "command": "...", "args": ["..."] },
    "tableau-workflow": {
      "command": "C:\\path\\to\\tableau-workflow\\run-server.bat",
      "args": []
    }
  }
}
```

Guardá. Tu archivo tiene que ser **JSON válido**: comas correctas entre entradas, llaves balanceadas.

> El snippet también está disponible en `claude_desktop_config.snippet.json` dentro del proyecto.

---

## 7. Instalar la Skill en Claude Desktop

Claude Desktop lee skills de un directorio configurable. En Windows, el lugar más común es:

```
%USERPROFILE%\.claude\skills\
```

Pasos:

1. Abrí el Explorador y pegá `%USERPROFILE%\.claude\` en la barra. Si la carpeta no existe, creala. Adentro creá una subcarpeta `skills\` si no existe.
2. Creá una subcarpeta `tableau-workflow\` (el nombre va a ser el ID de la skill).
3. Copiá adentro **el contenido** de `tableau-workflow\skill\`. La estructura final debe verse así:

```
%USERPROFILE%\.claude\skills\tableau-workflow\
├── SKILL.md
├── workflows\
│   └── refresh.md
└── references\
    └── twb-xml-anatomy.md
```

Alternativa cómoda (PowerShell, abrir como Administrador no es necesario):

```powershell
$src  = "C:\path\to\tableau-workflow\skill"
$dst  = "$env:USERPROFILE\.claude\skills\tableau-workflow"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Path "$src\*" -Destination $dst -Recurse -Force
```

> Si tu Claude Desktop lee skills de otra carpeta (algunas builds usan `%APPDATA%\Claude\skills\` o un path configurado por settings), repetí lo mismo en esa ubicación. Si dudás, abrí Settings de Claude Desktop y mirá qué carpeta tiene configurada para skills.

---

## 8. Reiniciar Claude Desktop

Cerrá completamente Claude Desktop (no minimizar — clic derecho en el icono de la bandeja → Quit). Reabrilo.

Verificá que el MCP cargó:
- En Settings → **Connectors** o **MCP**, deberías ver `tableau-workflow` con punto verde.
- Si está en rojo, mirá los logs en `%APPDATA%\Claude\logs\` para ver qué falla.

---

## 9. Smoke test desde Claude

Abrí un chat nuevo en Claude Desktop y probá uno por uno:

1. **Conectividad**:
   > "Usá el tool `site_info` del MCP tableau-workflow y mostrame qué devuelve."

2. **Discovery**:
   > "Listame las datasources publicadas del proyecto X" (Claude llama `list_datasources`).

3. **Skill activa**:
   > "Refresh the `your-datasource-name` datasource and tell me when it finishes."
   >
   > Claude debe identificar que es el workflow de refresh (la skill lo guía), localizar la datasource via `list_datasources`, y llamar `refresh_and_wait`.

4. **Catálogo (primera vez tarda 5-15min para 50-100 workbooks)**:
   > "Buildeá el catálogo de Tableau usando mi carpeta local y todo Cloud."

---

## Troubleshooting rápido

| Síntoma | Causa probable | Fix |
|---|---|---|
| `verify.bat` dice **401** | PAT expirado o nombre mal | Regenerá el PAT en Tableau Cloud y actualizá `.env` |
| MCP en rojo en Claude Desktop | El `run-server.bat` tira error al inicio | Mirá `%APPDATA%\Claude\logs\` — probablemente .env mal armado o falta el venv |
| Claude no encuentra la skill | La carpeta `~/.claude/skills/` no es la que lee tu build | Probá `%APPDATA%\Claude\skills\` y revisá Settings |
| `python` no se reconoce dentro de `cmd` | Python no quedó en PATH | Reinstalá Python tildando "Add Python to PATH" o agregá manualmente |
| `pip install` falla | Firewall/proxy o pip viejo | `python -m pip install --upgrade pip` y reintentar |
| Catálogo tarda demasiado | 100+ workbooks en Cloud | Usá `build_catalog(project_id="...")` para indexar solo un proyecto primero |

---

## Próximos pasos (post-Fase 1)

Una vez que tengas Fase 1 funcionando en tu día a día (refresh + búsqueda en catálogo + análisis de workbooks), el plan es:

- **Fase 2** — `clone_and_remap`: implementar `workbook_editor.py` con `swap_datasource`, `remap_fields`, `validate_structural`. Ver §8 del SDD.
- **Fase 3** — Bug Fix + Composición: API granular de filtros + `composer.py` multi-source. Ver §5.5, §5.6, §6.3, §6.4 del SDD.

Cuando vuelvas para arrancar Fase 2, pedime que continúe desde acá.
