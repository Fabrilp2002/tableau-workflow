# Fix-Broken-Dashboard — End-to-End Methodology

Workflow probado en producción para arreglar dashboards que muestran datos incorrectos, fields rotos, o counts que no matchean la base de datos. Esta guía sintetiza lo aprendido fixeando 5 dashboards (Bray, Polaris, Older Persons, Signal CFN, UK New) en una misma sesión.

## When to use

User dice cosas como:
- "el dashboard muestra X familias pero deberían ser Y"
- "no me aparecen los datos de la organización Z al filtrar"
- "los campos están en rojo en Tableau Desktop"
- "el extract no se refresca / no me da los datos actualizados"
- "los porcentajes están raros / monthly income dice todo `<£100`"

## Core principles

1. **Verificar Postgres baseline primero** — todo diagnóstico arranca con: ¿qué dice realmente la base de datos para este survey/org/dimension? Conecta vía `psycopg2` y query directo.
2. **Backup antes de modificar** — `download_workbook` + `download_datasource(include_extract=True)` a una carpeta dedicada. Siempre.
3. **Diagnose top-down, fix bottom-up** — primero entendé qué está mal (workbook? DS? extract? schema?), después fixea la capa más baja primero.
4. **Verificar visualmente via CSV download** — antes de declarar "arreglado", bajá CSV del view publicado con `populate_csv()` y compará con Postgres.
5. **Publicar a un proyecto de prueba primero** — usar `TESTING` project como sandbox antes de overwrite de producción.

## The 5 bug categories observed

### 1. Embedded extract stale (cache local del workbook con datos viejos)

**Síntoma**: el workbook muestra N families, pero la DS publicada tiene M > N families. Refrescar el DS no cambia el workbook.

**Diagnóstico**: el `.twb` interno del `.twbx` tiene `<extract enabled='true'>` con un `<refresh-event timestamp-start='YYYY-MM-DD'>` viejo. Esto bloquea la lectura del DS publicada.

**Fix**: editar el XML para cambiar a `<extract enabled='false'>` y eliminar el `.hyper` interno del `.twbx`. El workbook pasa a leer en vivo del sqlproxy del DS publicada.

### 2. Schema case mismatch (camelCase ↔ lowercase)

**Síntoma**: campos como `[areaOfResidence]`, `[attainedLevel]` aparecen en **rojo** con `⚠` en el panel Data, pero las versiones lowercase (`areaofresidence`) sí funcionan.

**Diagnóstico**: el workbook fue diseñado con aliases SQL camelCase entre comillas dobles. Pero el Cloud connector cuando hace create_extract **normaliza todos los nombres a lowercase**, rompiendo las referencias.

**Fix**: regenerar el `.hyper` LOCALMENTE con `psycopg2` (que respeta los aliases exactos del SQL). Bundlear en `.tdsx`. Publicar overwrite SIN `auto_extract` (para que Cloud no re-genere el extract y normalice).

### 3. Filtros hardcoded en SQL del DS

**Síntoma**: el dashboard nunca trae cierta org/proyecto/categoría aunque exista en Postgres y no haya filtros visibles activos.

**Diagnóstico**: el SQL custom del DS tiene una clausula `WHERE` con valores hardcoded — típico patrón es `s.organization_id = 27` que excluye silenciosamente otras orgs.

**Fix**: actualizar el SQL del `.tds` para remover el filtro hardcoded. Republicar overwrite preservando el LUID.

### 4. Context filters hardcoded en el `<shared-view>` del workbook

**Síntoma**: incluso después de "eliminar todos los filtros visibles" en Tableau Desktop, el count sigue mal.

**Diagnóstico**: el `.twb` XML tiene `<filter context='true'>` blocks con `<groupfilter function='member' member='"X"'>` enumerados. Estos se crearon con "Add to context → Show only existing values" y NO aparecen como pills visibles. Cuando aparecen datos nuevos (org nueva, project nuevo, etc.), quedan invisibles.

**Filtros típicos a vigilar**:
- `country_of_birth` IN (lista hardcoded) → excluye nulls y países nuevos
- `project` IN (NULL, "X") → excluye projects nuevos
- `Max Survey Number (copia) = "2 or more Survey"` → excluye families con solo 1 survey
- `housingSituation` lista enumerada → excluye valores nuevos
- `organization (copia)` enumerated members
- `geo_latitude (copia)` con 90+ members ← red flag típico

**Fix**: strip estos filters del XML matcheando por column name fragment (NO por regex genérica que rompe sheets).

### 5. Calc bins con valores legacy

**Síntoma** (caso Polaris): el dropdown muestra orgs nuevas (porque `values='database'`) pero al seleccionarlas no filtra correctamente.

**Diagnóstico**: el dropdown está bound a un `calculated bin` (e.g. `[organization (grupo)]`) que solo conoce las orgs legacy del momento del publish. Los buckets auto-generados para orgs nuevas no matchean con los labels del dropdown.

**Fix**: cambiar las `<zone param='...'>` para que apunten al campo raw (`[organization]`) en lugar del calc bin.

## The end-to-end workflow (60-90 min total)

### Phase 1 — Diagnose (15 min)

```python
# Step 1: Validate Postgres baseline
import psycopg2
URL = "postgresql://fp_psp_db:fp_psp_db@<host>:5432/<db>"
# Query: how many families/surveys/orgs for this survey_definition_id?
# Compare to dashboard numbers.

# Step 2: List Cloud assets
list_workbooks(project_id=...)
list_datasources(project_id=...)

# Step 3: Backup
mkdir _backup_original/
download_workbook(wb_id, save_dir=...)
download_datasource(ds_id, save_dir=..., include_extract=True)

# Step 4: Inspect schemas
# - Extract bundled in workbook .twbx (the cached hyper)
# - Extract from published DS
# - SQL inside .tds
# Look for camelCase vs lowercase, hardcoded WHERE, extract block enabled, etc.
```

### Phase 2 — Build new DS (15 min)

Cuando hay schema mismatch o hardcoded SQL filters:

```python
# Generate .hyper LOCALLY with psycopg2 (preserves SQL aliases)
# Build SQL with explicit camelCase aliases between double quotes:
#   SELECT ... ->> 'areaofresidence' AS "areaOfResidence"
# Use psycopg2.cursor.description to auto-discover columns

# Then bundle in .tdsx using existing DS .tds as template:
#   - Strip <metadata-records>, <extract>, <aliases> blocks
#   - Replace <relation type='text'> SQL with corrected version
#   - Bundle the locally-built .hyper

# Publish with TSC directly (NOT MCP tool — escape bugs):
result = server.datasources.publish(
    TSC.DatasourceItem(project_id=..., name='exact-name'),
    tdsx_path,
    mode=TSC.Server.PublishMode.Overwrite,
    connection_credentials=TSC.ConnectionCredentials(
        'fp_psp_db', 'fp_psp_db', embed=True
    )
)
# DO NOT use auto_extract=True if you want camelCase preserved.
```

### Phase 3 — Clean workbook XML (10 min)

```python
# Surgical strip — by EXACT column name fragments, not generic regex:
PROBLEMATIC = [
    "country_of_birth", ":project:", "Max Survey Number (copia)",
    "Calculation_797700104190308354", "employmentstatusprimary (group)",
    ":housingSituation:", "Calculation_2575214576219492352",
    "geo_latitude (copia)", "organization (copia)",
]
# For each filter, check if column attr contains any fragment → strip.
# Also: disable embedded extract (<extract enabled='true'> → 'false').
# Also: strip <shelf-sort-v2 .../> orphan blocks (cause publish warnings).
```

### Phase 4 — Test in TESTING project (10 min)

**Critical step** — never publish directly to production:

```python
# Publish to TESTING project as "<name> QA TEST"
item = TSC.WorkbookItem(project_id=TESTING_ID, name=f"{orig_name} QA TEST")
result = server.workbooks.publish(item, twbx_path,
    mode=TSC.Server.PublishMode.Overwrite,
    skip_connection_check=True)

# Verify via CSV download — this is the ground truth:
server.workbooks.populate_views(result)
for view_name in ['Snapshot.Total Familes', 'survey_count_by_organisation', 'Profile']:
    v = next((x for x in result.views if x.name == view_name), None)
    server.views.populate_csv(v)
    # Parse CSV, count families/surveys/etc, compare to Postgres baseline.
```

Expected: counts en el CSV deben matchear Postgres exactly.

### Phase 5 — Promote to prod (5 min)

Solo si Phase 4 pasó:

```python
# Publish to original project with overwrite (preserves LUID)
item = TSC.WorkbookItem(project_id=ORIG_PROJECT_ID, name=orig_name)
result = server.workbooks.publish(item, twbx_path,
    mode=TSC.Server.PublishMode.Overwrite,
    skip_connection_check=True)

# Delete the QA TEST workbook
server.workbooks.delete(qa_wb_id)
```

### Phase 6 — Verify daily refresh works (5 min)

Disparar refresh manual sobre el DS publicado y poll until updated_at changes:

```python
ds = server.datasources.get_by_id(ds_id)
baseline = str(ds.updated_at)
server.datasources.refresh(ds)
# poll every 15s until updated_at != baseline
# Typical: 40-100 seconds
```

Esto confirma que los daily schedules funcionarán (mismo authentication path).

## Tableau Cloud limitations (workarounds)

| Limitación | Workaround |
|---|---|
| No se pueden crear schedules de refresh via REST API en Cloud (`schedule is null`) | Crear via UI: DS page → Extract Refreshes → New Extract Refresh |
| No se pueden listar schedules globales (`Admin schedules are not supported`) | Inspeccionar el XML raw de un task existente para ver el schedule inline |
| `auto_extract=True` normaliza nombres a lowercase | Bundlear `.hyper` local en `.tdsx` y publicar con `auto_extract=False` |
| MCP tool `publish_datasource` escapa `&` mal en nombres | Usar TSC directo: `server.datasources.publish()` |
| `refresh_and_wait` falla con `'JobItem' object has no attribute 'status'` | Poll `updated_at` change manualmente |
| Job query for `create_extracts` jobs falla en REST API | Usar poll de `updated_at` o `has_extracts` change |
| Workbook publish da error con shelf-sorts huérfanos | Strip `<shelf-sort-v2/>` self-closing blocks |
| `"Unable to connect to published data source to refresh data. Allow refresh access"` | Re-publicar workbook desde Desktop con "Allow refresh access" tildado |

## Common Postgres query patterns

```sql
-- How many families/surveys in this survey?
SELECT COUNT(DISTINCT s.family_id) families,
       COUNT(DISTINCT s.id) surveys,
       COUNT(DISTINCT s.organization_id) orgs
FROM data_collect.snapshot s
JOIN ps_families.family f ON s.family_id = f.family_id
WHERE s.survey_definition_id = <ID> AND f.is_active IS TRUE;

-- Org distribution
SELECT org.id, org.name, COUNT(DISTINCT s.family_id) families
FROM data_collect.snapshot s
JOIN ps_network.organizations org ON s.organization_id = org.id
JOIN ps_families.family f ON s.family_id = f.family_id
WHERE s.survey_definition_id = <ID> AND f.is_active IS TRUE
GROUP BY org.id, org.name;

-- Apply the same filters Tableau is applying (debug)
WITH base AS (
  SELECT DISTINCT s.family_id FROM data_collect.snapshot s
  JOIN ps_families.family f ON s.family_id = f.family_id
  LEFT JOIN ps_families.family_members m ON f.family_id = m.family_id AND m.first_participant IS TRUE
  LEFT JOIN system.countries cob ON cob.alfa_2_code = m.birth_country::bpchar
  LEFT JOIN ps_network.projects p ON s.project_id = p.id
  WHERE s.survey_definition_id = <ID> AND f.is_active IS TRUE
    AND cob.country IN ('Ireland', 'United Kingdom')  -- the suspected filter
    AND (p.title IS NULL OR p.title = 'B&NWAP')
)
SELECT COUNT(*) FROM base;
-- Compare result to what dashboard shows
```

## Pre-flight checklist

Antes de tocar producción:

- [ ] Postgres baseline counts validados
- [ ] Backup local del workbook + DS original existe
- [ ] Schema (DS publicada) inspeccionado (.hyper inside) — confirmado qué columns están
- [ ] Modificaciones planeadas listadas explícitamente
- [ ] Publicado a TESTING project primero
- [ ] CSV download del TESTING workbook matchea Postgres
- [ ] Autorización del usuario explícita para overwrite de producción

## Anti-patterns (no hacer)

- ❌ Strip regex genérica de `<filter context='true'>` — rompe sheets que dependen de los filters
- ❌ Stripear sin antes haber probado en TESTING
- ❌ Usar `auto_extract=True` cuando hay camelCase aliases que querés preservar
- ❌ Hacer overwrite del workbook prod antes de validar CSV en TESTING
- ❌ Confiar en `has_extracts` y `consecutive_failed_count` como única señal — siempre disparar un refresh manual para confirmar
- ❌ Asumir que "todos los filtros eliminados" significa "no hay filtros" — el embedded extract cache puede tener los datos ya pre-filtrados
- ❌ Cambiar el `name` del DS al republicar — usa **exactamente** el mismo name + project para preservar el LUID

## Real cases solved with this method (May 2026)

| Dashboard | Bug encontrado | Tiempo total |
|---|---|---|
| Polaris - Rede De Empresas 2.0 | DS sin extract + workbook con calc bin legacy orgs | 90 min |
| Older Persons (Signal) | DS apuntaba a survey wrong + sin extract refrescable | 60 min |
| Signal CFN | DS sin embed_password | 15 min |
| ds_united_kingdom_new | DS sin embed_password, schedule suspendido | 15 min |
| Signal - Bray & North Wicklow | TODOS los bugs simultáneos (categorías 1-5) | 120 min |

El de Bray fue el más complejo. Tenía:
- Embedded extract del 29-abril con 728 rows hardcoded
- Schema mismatch camelCase vs lowercase (los 8 fields económicos)
- SQL del DS con `organization_id = 27` hardcoded
- 23 context filters problemáticos + 90 filter blocks en total (incluyendo `geo_latitude (copia)` con 94 members enumerados)
- Workbook publicado sin "Allow refresh access"

End result: 22 families (de 12 anteriores), 24 surveys, todos los campos verdes, refresh manual confirmado en 42-108s.

## References

- `workflows/refresh.md` — basic refresh workflow
- `references/twb-xml-anatomy.md` — XML structure reference
- `SDD.md` — full design doc
