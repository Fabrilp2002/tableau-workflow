# Tableau Workflow Assistant

MCP Server + Skill to automate repetitive Tableau Cloud workflows from inside Claude Desktop / Claude Code. Built for analysts who manage 20-100+ workbooks across multiple surveys/datasources and routinely need to refresh extracts, fix broken dashboards, clone workbooks to point at new datasources, and compose new dashboards from sheets that live in several existing workbooks.

**Author**: Fabrizio López Parzajuk

**Original use case**: large fleet of Tableau dashboards built on a community-survey methodology (multiple country-specific surveys, ~50 indicators each, mixed Spanish/English content). The tool is generic and works with any Postgres-backed Tableau Cloud setup.

## Estado del proyecto

**Fase 1 (este release) — Foundation + Discovery + Refresh**

✅ Conectividad a Tableau Cloud + autenticación con PAT
✅ Listados (proyectos, workbooks, datasources)
✅ Parser de `.twb` / `.twbx` (extrae datasources, parámetros, calc fields, sheets, dashboards)
✅ Field matcher para comparar dos datasources (exact + normalized + fuzzy + samples)
✅ Catálogo persistente: indexa todos tus workbooks (Cloud + carpeta local) en un JSON búsqueda-friendly
✅ Refresh + monitoreo de jobs
✅ Backup automático antes de operaciones destructivas
✅ Skill con workflow de refresh + referencia de XML anatomy

**Fase 2 (próxima)**
- `swap_datasource` + `remap_fields` (clone+remap completo)
- Editor de XML para fórmulas de calc fields
- Republish con validación pre-publish

**Fase 3**
- Bug fixes quirúrgicos (filter context, aggregation, calc field repair)
- Composición: tomar N sheets de M workbooks → nuevo dashboard
- Skill playbooks completos

## Arquitectura

```
┌────────────────────────────────────┐
│      Claude (Desktop / Code)       │
└──────┬─────────────────────────────┘
       │
       ▼  (usa skill como guía + tools del MCP)
┌────────────────────────────────────┐
│  SKILL: tableau-workflow           │
│  - SKILL.md (entry)                │
│  - workflows/refresh.md            │
│  - references/twb-xml-anatomy.md   │
└──────┬─────────────────────────────┘
       │
       ▼  (llama tools)
┌────────────────────────────────────┐
│  MCP SERVER (server.py)            │
│                                    │
│  ├── tableau_client.py             │  ← REST API + Metadata API
│  ├── workbook_parser.py            │  ← Parsea .twb XML
│  ├── field_matcher.py              │  ← Compara datasources
│  └── catalog.py                    │  ← Índice persistido
└──────┬─────────────────────────────┘
       │
       ▼
┌────────────────────────────────────┐
│  Tableau Cloud  +  carpeta local   │
└────────────────────────────────────┘
```

## Instalación

```bash
# 1. Clonar / copiar la carpeta
cd tableau-workflow

# 2. Dependencias
pip install -r requirements.txt

# 3. Credenciales
cp .env.example .env
# Editar .env con tu URL, site, PAT y carpeta local de .twb

# 4. Crear el PAT en Tableau Cloud
# Avatar (arriba derecha) → My Account Settings → Personal Access Tokens
# Crear con nombre "mcp-workflow", copiar el secret en TABLEAU_PAT_VALUE
```

## Configuración en Claude Desktop

Editar `claude_desktop_config.json`:

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Mac**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "tableau-workflow": {
      "command": "python",
      "args": ["C:/ruta/completa/a/tableau-workflow/server.py"]
    }
  }
}
```

Las variables de entorno se leen del `.env` automáticamente.

## Configuración en Claude Code

Agregar al `~/.claude/config.toml` o equivalente:

```toml
[mcp_servers.tableau-workflow]
command = "python"
args = ["/ruta/a/tableau-workflow/server.py"]
```

## Herramientas disponibles (Fase 1)

### Conectividad
- `site_info()` — verificar credenciales y versión del sitio
- `list_projects()`, `list_workbooks(project_id)`, `list_datasources(project_id)`

### Inspección de workbooks
- `get_datasource_fields(datasource_id)` — campos de una datasource (Metadata API)
- `download_workbook(workbook_id)` — descarga el `.twb` localmente
- `parse_workbook(twb_path)` — análisis completo del XML
- `workbook_summary(twb_path)` — versión rápida del análisis

### Refresh
- `refresh_datasource(datasource_id)` — dispara refresh
- `check_refresh_job(job_id)` — consulta estado
- `refresh_and_wait(datasource_id, timeout_seconds)` — combo

### Catálogo
- `build_catalog(local_folder, project_id)` — indexa todo
- `catalog_stats()` — estadísticas del índice
- `list_indexed_workbooks()`, `get_workbook_details(entry_id)`
- `search_catalog(query, workbook_filter, mark_type, source)` — búsqueda

### Comparación
- `compare_datasources(old_id, new_id)` — propone mapping con confidence scores

### Backup
- `backup_workbook(workbook_id)` — copia con sufijo de fecha

## Cómo se ve usándolo

**Simple refresh:**
```
> Refresh the "Survey-RegionA" datasource and let me know when done
[Claude calls: list_datasources, finds "Survey-RegionA",
 calls refresh_and_wait → reports result]
```

**Explore a workbook:**
```
> Show me what the "Region A Dashboard" workbook contains
[Claude calls: search_catalog("Region A"), get_workbook_details(entry_id),
 reports: 99 sheets, 12 dashboards, 86 calc fields, 4 parameters]
```

**Prepare a clone+remap (Phase 2 completes it, Phase 1 prepares it):**
```
> I want to clone the "Region A" dashboard for the "Region B" survey
[Claude calls: compare_datasources(region_a_id, region_b_id) →
 reports: 92% auto-applicable, 5 fields need confirmation, 1 unmatched]
```

## Limitaciones conocidas

1. **Fase 1 es solo lectura + refresh + análisis**. Las modificaciones de workbooks llegan en Fase 2.
2. **Indexar Cloud es lento** la primera vez: descarga + parsea cada workbook. Para 50 workbooks puede tardar 5-10 minutos.
3. **Metadata API requiere permisos** de Creator. Si tu PAT es de Explorer, `get_datasource_fields` puede fallar; el fallback es parsear el `.twb` descargado.
4. **PATs expiran tras 15 días de inactividad**. Si ves errores 401 después de tiempo sin usar, regenerar.

## Estructura del proyecto

```
tableau-workflow/
├── server.py                        # MCP server (entry point)
├── tableau_client.py                # REST + Metadata API wrapper
├── workbook_parser.py               # Parser .twb / .twbx
├── field_matcher.py                 # Comparación de datasources
├── catalog.py                       # Índice persistente
├── requirements.txt
├── .env.example
├── README.md
└── skill/
    ├── SKILL.md                     # Entry point de la skill
    ├── workflows/
    │   └── refresh.md               # Playbook de refresh
    └── references/
        └── twb-xml-anatomy.md       # Anatomía del XML de Tableau
```
