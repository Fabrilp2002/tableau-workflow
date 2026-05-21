# Software Design Document
## Tableau Workflow Assistant

| | |
|---|---|
| **Proyecto** | Tableau Workflow Assistant |
| **Autor** | Fabrizio López Parzajuk |
| **Contexto** | your organization — Data Analyst |
| **Fecha** | 18 de mayo de 2026 |
| **Versión** | 1.2 |
| **Estado** | Fase 1 implementada, Fases 2 y 3 pendientes |
| **Cambios v1.1** | Reescritura de §2.2 (composición pasa de 2-3 charts → N sheets de M workbooks, multi-tab, con cross-version indicator mapping). Ajustes propagados a §1, §2.4, §4, §5.6, §6.4, §8, §16, §17. |
| **Cambios v1.2** | Rework del bug fix para reflejar variabilidad real: §2.1 punto 2 reescrito con familias de bugs; §5.5 con API granular de filtros (10 acciones + diagnose_filters) en lugar de fix_filter_context monolítico; §6.3 convertido en árbol diagnóstico con ramas; §10.4 nueva con taxonomía de FilterIssue y heurísticas; §10.1 ampliada; §8 entregables y criterios de aceptación actualizados. |
| **Cliente AI** | Claude Code + Claude Desktop + Cowork |

---

## 1. Resumen ejecutivo

Sistema modular (MCP Server + Skill) que automatiza las tres tareas repetitivas de mayor frecuencia en mi trabajo con Tableau en your organization: refrescar datasources, arreglar bugs en dashboards existentes, y clonar dashboards para nuevas encuestas del programa survey program cambiando la datasource y adaptando todas las referencias de campos. Como capacidad adicional, permite **componer workbooks curados a partir de múltiples sheets tomados de múltiples workbooks fuente** — el caso de uso guía es el ensamble del "Public Shared Insight Dashboard": un workbook público multi-tab que combina ~10-15 charts seleccionados desde 5-8 templates distintos de survey (Survey-V2, Survey-V3, Region A, Older Adults, Easy-Read variant, Young Adults, COVID-19), todos apuntados a una datasource elegida y con cross-version indicator mapping resuelto.

El sistema opera contra **Tableau Cloud** vía REST API + Metadata API, y contra una **carpeta local** de archivos `.twb`/`.twbx` (OneDrive). Se invoca desde clientes MCP de Anthropic (Claude Code, Claude Desktop, Cowork) usando lenguaje natural; los workflows están guiados por una Skill que asegura comportamiento consistente.

---

## 2. Problema y contexto

### 2.1 Trabajo manual repetitivo a automatizar

Mi rol como Data Analyst implica recurrentemente tres tareas operativas:

1. **Refresh de datasources publicadas** en Tableau Cloud. Operación simple pero hoy es clic a clic, una por una, y requiere verificar manualmente que terminó.

2. **Resolución de bugs en dashboards existentes**. No hay un bug "típico" — hay familias de bugs y cada caso requiere diagnóstico antes de acción. Las familias más frecuentes:

   - **Bugs de filtros** (la familia más diversa, ver taxonomía en §10.4):
     - El filtro existe pero no está aplicado al sheet correcto (aplica solo al worksheet activo cuando debería aplicar al dashboard).
     - El filtro no está en context filter y debería estarlo (filter-group='2'), o al revés.
     - El filtro está pero su `apply-to-worksheets` no incluye todos los sheets que comparten datasource.
     - El filtro afecta a un sheet pero no a su tooltip / acción asociada.
     - El filtro es de tipo equivocado para el campo (categorical sobre un campo continuo, range sobre un boolean).
     - El filtro tiene scope cross-datasource mal definido (`datasource` vs `all using related data sources`).
     - Filter actions de dashboard que no propagan a sheets target.
     - Filtros con valores hardcodeados que ya no existen en la datasource (se ven vacíos sin error).
     - Orden de filter execution mal: dimension filter después de measure filter cuando se necesitaba al revés.
   - **Bugs de calc fields**: dejan de resolverse cuando un campo subyacente cambió de nombre, fórmulas con paréntesis mal cerrados que Tableau acepta pero devuelven null, LOD expressions con la dimensión equivocada en el FIXED.
   - **Bugs de agregación**: campos que devuelven null o valores absurdos por mezcla de granularidades (SUM sobre algo que ya está pre-agregado en la datasource), ratios calculados sobre el grano equivocado.
   - **Bugs de conexión / datasource**: la datasource publicada cambió de LUID o nombre, el workbook quedó apuntando al ID viejo; refs cruzadas a datasources eliminadas.
   - **Bugs de parámetros**: parámetro con `current_value` fuera de `allowed_values`, parámetros referenciados que ya no existen en `<datasource name='Parameters'>`.
   - **Bugs de layout / interactividad**: zone de dashboard que referencia un sheet renombrado, action filters apuntando a sheets que ya no están.

   El sistema **no** asume cuál de estos es el problema. Diagnostica primero (parser + heurísticas + a veces consulta al usuario), propone hipótesis, y aplica la corrección apropiada — que puede ser muy distinta entre casos.

3. **Clone + Remap entre encuestas**. La más frecuente y la que más tiempo consume. El programa survey program de your organization tiene encuestas que se aplican en distintos países/proyectos. Para cada nueva encuesta tomo un dashboard existente que funciona, cambio la datasource por la nueva, y adapto manualmente todas las referencias de campos en: rows, cols, filtros, calc fields, parámetros. Es trabajo mecánico pero extenso (un workbook típico tiene ~80 calc fields y ~100 sheets).

### 2.2 Capacidad adicional deseada — Composición multi-source

**Composición**: tomar **N sheets desde M workbooks fuente distintos** (no limitado a 2-3) y ensamblarlos en un **workbook nuevo, potencialmente multi-tab**, apuntando a una datasource elegida. La operación arrastra todas las dependencias necesarias (calc fields directos y transitivos, parámetros, filtros, aliases), resuelve conflictos de naming entre fuentes, y aplica un cross-version indicator mapping para que los mismos indicadores conceptuales (ej. "stable income") apunten al campo correcto del target sin importar cómo se llamen en cada workbook origen.

**Caso de uso guía — "Public Shared Insight Dashboard"** (documentado en `commissioning_notes.docx` + `project_budget.pdf`):

Construir un workbook público con **dos tabs/sheets de presentación** ("Where are we now?" y "What has changed?"), cada uno conteniendo entre 5 y 7 charts curados que se toman de templates existentes. Los charts a ensamblar incluyen:

*Tab 1 — Where are we now?* (snapshot actual):
1. Introductory Overview (gender, age, education, employment, housing) — de Survey-V2
2. Indicator Overview (donut/pie Red/Amber/Green) — de Survey-V2 / CFN
3. Challenges vs Strengths (% Red por indicador / % Green por indicador) — adaptado de Survey-Standard
4. Ranked Indicators top 10 (por nivel de challenge) — de Survey-V2
5. Prioritised Indicators (qué priorizan los participantes) — de Survey-V2
6. Dimensions Overview (patrones por dimensión survey) — de Older Adults / Easy-Read variant
7. Map Overview (con tooltip refinement) — de Region A

*Tab 2 — What has changed?* (movimiento longitudinal):
1. Survey Indicator Comparison (movimiento R/A/G entre encuestas) — de Region A
2. Most Improved Indicators — de Survey-Standard
3. Dimensions Before and After — de Older Adults
4. Maps Before and After — de Region A
5. Key Socioeconomic Comparisons (housing, employment) — de Young Adults / Survey-V2

*Feature opcional — Human Agency Score*: vista composite calculada sobre tres indicadores (self-esteem, autonomy, self-expression). Requiere que el composer pueda **generar un calc field nuevo** que agregue indicadores que existen en las datasources fuente pero no estaban combinados en ningún template original.

**Reglas adicionales del caso público**:
- Métricas en **porcentajes**, no en valores absolutos (puede requerir reescritura de fórmulas en calc fields al pasar de template interno → público).
- **No** llevar filtros de organización/proyecto del template fuente — el composer debe poder descartarlos.
- Whitelist de filtros públicos: survey number, ethnic group, age, area of residence, gender, education.
- El target apunta a una sola datasource pública (PostgreSQL AWS RDS) que tiene un subset consolidado de los indicadores presentes en las versiones fuente.

**Insumos que el composer aprovecha**:
- `survey_comparison.xlsx` — cross-reference de qué indicadores existen en cada versión de survey y cómo se nombran en cada una (input para el `IndicatorMapping` registry, ver §5.6).
- Catálogo (`catalog.py`) — para localizar sheets/workbooks fuente sin tener que reparsearlos.
- Field matcher (`field_matcher.py`) — para resolver nombres distintos entre fuentes y target.

**Por qué esto no es un "clone+remap" más grande**:
- Clone+remap toma **un** workbook fuente y cambia su datasource → preserva estructura.
- Composición toma **fragmentos de N workbooks** y los fusiona en una estructura **nueva** (con su propio layout de dashboards, sus propios filtros, calc fields potencialmente combinados/renombrados, parámetros mergeados con resolución de conflictos).
- Los riesgos son distintos: en clone+remap el riesgo principal es el mapeo de campos; en composición se suman conflictos entre fuentes, dependencias transitivas, y validación cross-tab.

### 2.3 Contexto Tableau

- Plan: **Tableau Cloud + Tableau Desktop**
- Workbooks: entre **20 y 100** entre Cloud y carpeta local
- Versión de archivos: format 18.1 (Tableau 2024-2025)
- Conexión a datasources publicadas vía `sqlproxy`
- MCP oficial de Tableau ya conectado (read-only)

### 2.4 Características del programa survey program

- 50 indicadores socioeconómicos con scores 1-3 (Money to live on, Stable Income, Bank account confidence, etc.) agrupados en 6 dimensiones (Income and Employment, Housing and Infrastructure, Health and Environment, Education and Culture, Organisation and Participation, Interiority and Motivation).
- Estructura del Excel fuente: 4 sheets — Familias, Miembros, Indicadores, Prioridades.
- **Hallazgo clave**: los Excels tienen dos filas de headers (nombre humano + nombre técnico camelCase). Los nombres técnicos son los que aparecen en el XML de los `.twb` y son **estables entre encuestas** para indicadores. Los campos demográficos (housing situation, ethnic group, etc.) sí varían.
- **Versiones de survey relevantes** (cada una tiene sus propios templates de Tableau con naming y green-levels propios): Survey-V2, Survey-V3, Survey-Standard, Survey RegionA, Older Adults, Survey Easy-Read variant, Survey Young Adults, COVID-19 variant.
- **Cross-version indicator mapping** (insumo `survey_comparison.xlsx`): tabla canónica que dice, por indicador (codename estable, ej. `stable_income`), qué nombre humano y qué green-level usa cada versión. Es la fuente de verdad para resolver "el mismo indicador conceptual" entre templates fuente distintos en una composición. El composer la consume; el field_matcher la usa como override para los casos de Familias/demográficos donde el fuzzy no alcanza.

---

## 3. Objetivos y no-objetivos

### 3.1 Objetivos

- Reducir tiempo manual en las 3 tareas a < 5 minutos cada una
- Consistencia: misma operación produce mismo resultado siempre
- Confiabilidad: nunca corromper un workbook publicado (backup + validación)
- Trazabilidad: cada operación deja registro de qué cambió
- Extensibilidad: arquitectura modular que permita agregar capacidades

### 3.2 No-objetivos (lo que el sistema NO hace)

- ❌ Generar desde cero dashboards complejos con muchos calc fields y parámetros. La complejidad real (~80 calc fields, 12 dashboards anidados) excede lo razonable para generación pura por XML templating.
- ❌ Reemplazar Tableau Desktop como interfaz primaria de diseño visual. El sistema modifica archivos; los retoques visuales siguen siendo manuales.
- ❌ Operar sobre datasources no publicadas (conexiones directas a bases en el workbook). Solo Published Datasources.
- ❌ Modificar permisos, sharing, ni configuración del sitio Tableau Cloud.

---

## 4. Vista general del sistema

```
┌─────────────────────────────────────────────────────────┐
│  CLIENTE AI (Claude Code | Desktop | Cowork)            │
└──────────────────┬──────────────────────────────────────┘
                   │  invoca con lenguaje natural
                   ▼
┌─────────────────────────────────────────────────────────┐
│  SKILL: tableau-workflow                                 │
│  • SKILL.md (entry + cuándo activar)                     │
│  • workflows/refresh.md                                  │
│  • workflows/bug-fix.md          [pendiente]             │
│  • workflows/clone-remap.md      [pendiente]             │
│  • workflows/compose-dashboard.md [pendiente]            │
│  • references/twb-xml-anatomy.md                         │
│  • references/common-bugs-catalog.md   [pendiente]       │
│  • references/semaforo-field-dictionary.md [pendiente]   │
│  • references/indicator-cross-version-map.md [pendiente] │
│  • references/filter-bug-taxonomy.md     [pendiente]     │
└──────────────────┬──────────────────────────────────────┘
                   │  guía a Claude para elegir tools
                   ▼
┌─────────────────────────────────────────────────────────┐
│  MCP SERVER: tableau-workflow                            │
│                                                          │
│  server.py (entry, FastMCP, 18+ tools)                  │
│      │                                                   │
│      ├── tableau_client.py                              │
│      │     • REST API (TSC)                             │
│      │     • Metadata API (GraphQL)                     │
│      │     • Auth con PAT                               │
│      │     • Refresh + jobs                             │
│      │     • Download/Publish                           │
│      │                                                   │
│      ├── workbook_parser.py                             │
│      │     • Parsea .twb y .twbx                        │
│      │     • Extrae datasources, params, calc fields,   │
│      │       sheets, dashboards                         │
│      │     • Detecta dependencias                       │
│      │                                                   │
│      ├── workbook_editor.py        [pendiente Fase 2]   │
│      │     • swap_datasource                            │
│      │     • remap_fields                               │
│      │     • fix_filter_context                         │
│      │     • update_calc_field_formula                  │
│      │     • validate_xml_structure                     │
│      │                                                   │
│      ├── field_matcher.py                               │
│      │     • Exact / case-insensitive / normalized      │
│      │     • Fuzzy (SequenceMatcher)                    │
│      │     • Sample-based (Jaccard de valores)          │
│      │                                                   │
│      ├── catalog.py                                     │
│      │     • Indexa todos los workbooks                 │
│      │     • Persiste en JSON                           │
│      │     • Búsqueda por descripción + filtros         │
│      │                                                   │
│      └── composer.py               [pendiente Fase 3]   │
│            • dependency resolution (transitiva)         │
│            • merge calc fields con conflict handling    │
│            • parameter merging                          │
│            • multi-tab dashboard layout (N sheets)      │
│            • cross-version IndicatorMapping registry    │
│            • filter whitelist/blacklist (público vs    │
│              interno)                                   │
│            • percentage rewrite (absoluto → %)          │
└─────────┬───────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────┐  ┌─────────────────────────────┐
│  Tableau Cloud          │  │  Carpeta local OneDrive     │
│  (REST + Metadata API)  │  │  (.twb / .twbx files)       │
└─────────────────────────┘  └─────────────────────────────┘
```

---

## 5. Especificación de componentes

### 5.1 `tableau_client.py` — Cliente Tableau Cloud

**Propósito**: Centralizar todas las llamadas a la REST API y la Metadata API de Tableau Cloud. Encapsular autenticación con Personal Access Token (PAT). Manejar sesiones con context manager.

**Interfaz pública**:

```python
class TableauClient:
    def __init__(self, server_url, site_name, pat_name, pat_value)
    def session()  # context manager
    
    # Listing
    def list_projects() -> list[dict]
    def list_datasources(project_id=None) -> list[dict]
    def list_workbooks(project_id=None) -> list[dict]
    
    # Workbook operations
    def download_workbook(workbook_id, save_dir=None) -> str  # local path
    def publish_workbook(twb_path, project_id, name, mode) -> dict
    def backup_workbook(workbook_id) -> dict  # copia con sufijo de fecha
    
    # Refresh + Jobs
    def refresh_datasource(datasource_id) -> dict  # retorna job_id
    def check_job(job_id) -> dict
    def refresh_and_wait(datasource_id, timeout_seconds=600) -> dict
    
    # Metadata
    def get_datasource_fields(datasource_id) -> dict  # vía GraphQL
    def site_info() -> dict
```

**Dependencias**: `tableauserverclient`, `os` (env vars), `tempfile`

**Estado**: ✅ Implementado

---

### 5.2 `workbook_parser.py` — Parser de .twb / .twbx

**Propósito**: Convertir un archivo `.twb` (XML) o `.twbx` (zip con .twb dentro) en una estructura Python navegable. Extraer todos los elementos relevantes y sus relaciones.

**Modelo de datos** (dataclasses):

```python
@dataclass
class Datasource:
    name: str           # nombre interno (ej: "sqlproxy.LUID")
    caption: str        # nombre humano
    inline: bool
    connection_class: str   # "sqlproxy" si es published
    connection_dbname: str  # LUID si es published
    connection_server: str
    is_published: bool

@dataclass
class Parameter:
    name: str
    caption: str
    datatype: str
    param_domain_type: str  # "list" | "range" | "any"
    current_value: str
    allowed_values: list

@dataclass
class CalcField:
    name: str           # nombre interno
    caption: str        # nombre visible
    datasource: str
    formula: str
    role: str           # "dimension" | "measure"
    datatype: str
    depends_on_fields: list[str]   # referencias [X] en la fórmula
    depends_on_params: list[str]   # referencias [Parameters].[X]

@dataclass
class Sheet:
    name: str
    datasources_used: list[str]
    fields_used: list[str]
    calc_fields_used: list[str]
    parameters_used: list[str]
    filters: list[str]
    context_filters: list[str]   # filter-group='2' en XML
    mark_type: str

@dataclass
class Dashboard:
    name: str
    sheets_used: list[str]
    zone_count: int

@dataclass
class ParsedWorkbook:
    twb_path: str
    version: str
    source_build: str
    datasources: list[Datasource]
    parameters: list[Parameter]
    calc_fields: list[CalcField]
    sheets: list[Sheet]
    dashboards: list[Dashboard]
```

**Interfaz pública**:

```python
class WorkbookParser:
    def parse(path: str) -> ParsedWorkbook  # acepta .twb o .twbx
```

**Algoritmo clave**: las referencias de campo se extraen con la regex `\[([^\[\]]+)\]`. Diferenciación entre campo y parámetro: si la referencia aparece como `[Parameters].[X]` → parámetro, sino → campo.

**Estado**: ✅ Implementado (con un refinamiento pendiente: los prefijos de agregación de Tableau tipo `pcto:sum:Calculation_xxx:qk:3` aún no se desempaquetan a su campo base)

---

### 5.3 `field_matcher.py` — Comparación de campos entre datasources

**Propósito**: Dadas dos listas de nombres de campo (datasource vieja y nueva), proponer un mapping con score de confianza para cada par. Habilita el clone+remap automático.

**Estrategia en 5 niveles**:

| Nivel | Método | Confidence | Ejemplo |
|---|---|---|---|
| 1 | Exact match | 1.00 | `survey_id` ↔ `survey_id` |
| 2 | Case-insensitive | 0.98 | `housingSituation` ↔ `HousingSituation` |
| 3 | Normalized (snake↔camel) | 0.92 | `householdMonthlyIncome` ↔ `household_monthly_income` |
| 4 | Fuzzy (SequenceMatcher) | 0.75–0.95 | `stableIncome` ↔ `stable_income_v2` |
| 5 | Sample-based (Jaccard) | refina #4 | comparar valores reales si nombres difieren |

**Umbrales por defecto**:
- `auto_apply_threshold = 0.95` — se aplica sin preguntar
- `fuzzy_threshold = 0.75` — se muestra al usuario con candidatos para confirmar
- < 0.75 → "no_match", se pide al usuario que provea el mapeo

**Interfaz pública**:

```python
class FieldMatcher:
    def match(old_fields, new_fields) -> list[FieldMatch]
    def refine_with_samples(match, old_samples, new_field_samples) -> FieldMatch
    def summarize(matches) -> dict  # estadística de auto/manual/unmatched
```

**Optimización para survey program**: dada la estabilidad de nombres técnicos en indicadores, el ratio esperado de auto-apply es 80-95%. Los demográficos requieren más confirmación manual.

**Estado**: ✅ Implementado

---

### 5.4 `catalog.py` — Índice persistente de workbooks

**Propósito**: Construir y mantener un catálogo en JSON con la "ficha técnica" de todos mis workbooks (Cloud + local). Permite búsqueda rápida por descripción ("gráfico de tendencia mensual") sin tener que reparsear archivos cada vez.

**Estructura del catálogo**:

```json
{
  "version": "1.0",
  "last_full_rebuild": "2026-05-18T19:00:00",
  "entries": {
    "local_a1b2c3d4e5f6": {
      "id": "local_a1b2c3d4e5f6",
      "source": "local",
      "identifier": "C:/OneDrive/Tableau/Survey-RegionA.twbx",
      "name": "Survey - Region A",
      "indexed_at": "...",
      "summary": {"sheets": 99, "dashboards": 12, "calc_fields": 86, ...},
      "datasources": [...],
      "parameters": [...],
      "calc_fields": [...],
      "sheets": [...],
      "dashboards": [...],
      "extra": {"file_size": ..., "modified": ...}
    }
  }
}
```

**Interfaz pública**:

```python
class WorkbookCatalog:
    def __init__(catalog_path)
    def index_local_folder(folder_path, recursive=True) -> dict
    def index_cloud(client, project_id=None) -> dict
    def full_rebuild(client, local_folder) -> dict
    def search(query, workbook_filter, mark_type, source) -> list[dict]
    def get_entry(entry_id) -> dict
    def list_entries() -> list[dict]
    def stats() -> dict
```

**Estrategia de indexación**: full rebuild una sola vez al inicio. Updates incrementales (TODO) cuando publicamos cambios.

**Estado**: ✅ Implementado (sin updates incrementales aún)

---

### 5.5 `workbook_editor.py` — Editor de XML *[Fase 2 — pendiente]*

**Propósito**: Modificar archivos `.twb` de forma controlada, preservando consistencia entre todos los lugares donde un campo o datasource es referenciado.

**Operaciones planificadas**:

```python
class WorkbookEditor:
    def __init__(twb_path)
    
    # --- Datasource & fields ---
    def swap_datasource(old_ds_name, new_ds_id, new_ds_caption) -> None
    def remap_fields(mapping: dict[str, str]) -> dict  # reporte de qué cambió
    
    # --- Filtros: API granular (no una sola fix_filter_context) ---
    # Cada bug de filtro tiene su acción correctiva; el diagnosticador
    # elige cuál(es) aplicar según el caso.
    def diagnose_filters(sheet_name: str | None = None) -> list[FilterIssue]
    # Si sheet_name es None, escanea TODOS los sheets del workbook.
    # FilterIssue contiene: tipo (enum), sheet, field, severidad, hipótesis,
    # fix_actions sugeridas con sus argumentos.
    
    def set_filter_context(sheet_name, filter_field, in_context: bool) -> None
    # filter-group='2' (in_context=True) o '1' (False)
    
    def set_filter_scope(sheet_name, filter_field, 
                        apply_to: Literal["worksheet", "all_using_this_ds", 
                                          "all_using_related", "specific"],
                        target_sheets: list[str] = None) -> None
    # Cambia el atributo apply-to-worksheets del filtro
    
    def change_filter_type(sheet_name, filter_field, 
                          new_type: Literal["categorical", "range", "relative", 
                                            "quantitative", "wildcard"]) -> None
    # Útil cuando el tipo de filter no matchea el tipo del campo
    
    def reorder_filters(sheet_name, new_order: list[str]) -> None
    # Cambia el orden de execution (dimension vs measure filter)
    
    def remove_stale_filter_values(sheet_name, filter_field) -> dict
    # Quita valores hardcodeados que ya no existen en la datasource;
    # consulta la datasource publicada para saber qué valores son válidos
    
    def fix_filter_action(dashboard_name, action_name, 
                         source_sheets: list[str], target_sheets: list[str], 
                         target_fields: list[str]) -> None
    # Bugs en filter actions de dashboard
    
    def promote_filter_to_dashboard(dashboard_name, sheet_name, filter_field) -> None
    # Toma un filter de un sheet y lo expone como filter de dashboard
    # (cambia su scope a "all_using_this_ds" o explícito sobre los sheets del dashboard)
    
    # --- Calc fields & agregación ---
    def update_calc_field_formula(calc_name, new_formula) -> None
    def change_aggregation(sheet_name, field, new_agg) -> None
    def fix_lod_dimension(calc_name, new_dimensions: list[str]) -> None
    
    # --- Parámetros ---
    def fix_parameter_value(param_name, new_current_value) -> None
    def add_parameter_allowed_value(param_name, value, alias=None) -> None
    
    # --- Layout / interactividad ---
    def rebind_dashboard_zone(dashboard_name, zone_id, new_sheet_name) -> None
    def remove_orphan_zone(dashboard_name, zone_id) -> None
    
    # --- Persistencia ---
    def save(output_path) -> str
    def validate_structural() -> list[str]  # lista de errores
```

**Modelo `FilterIssue`**:

```python
class FilterIssueType(Enum):
    NOT_IN_CONTEXT_BUT_NEEDS_TO_BE = "filter_not_in_context"
    IN_CONTEXT_BUT_SHOULDNT_BE = "filter_unnecessarily_in_context"
    SCOPE_TOO_NARROW = "filter_only_local"           # aplica solo a este sheet, pero otros sheets del dashboard usan misma ds
    SCOPE_TOO_BROAD = "filter_too_broad"             # aplica a sheets que no lo necesitan
    TYPE_MISMATCH = "filter_type_mismatch"           # categorical en campo continuo, etc.
    STALE_VALUES = "filter_stale_values"             # valores que ya no existen en ds
    ORDER_DEPENDENCY = "filter_order_dependency"     # measure filter antes que dimension filter
    ACTION_BROKEN = "dashboard_action_broken"        # filter action apunta a sheet inexistente
    NOT_APPLIED_AT_DASHBOARD_LEVEL = "filter_should_be_dashboard_level"  # filtro suelto cuando debería ser global del dashboard
    CROSS_DS_MISCONFIGURED = "filter_cross_ds_wrong" # relación entre datasources mal definida

@dataclass
class FilterIssue:
    type: FilterIssueType
    sheet_name: str | None       # None si es a nivel dashboard
    dashboard_name: str | None
    filter_field: str
    severity: Literal["info", "warning", "error"]
    hypothesis: str              # texto humano: "Este filtro está aislado al sheet 
                                 #  X pero el dashboard tiene Y, Z que usan la misma 
                                 #  datasource — probablemente debería propagarse"
    fix_actions: list[FixAction] # lista de acciones POSIBLES, en orden de plausibilidad
    requires_user_confirmation: bool  # True si la acción no es obvia
```

**Por qué API granular en vez de un `fix_filter_context` monolítico**: los bugs de filtros tienen al menos 10 variantes (ver §10.4). Una sola función no puede modelar correctamente las decisiones de cada caso — el composer del Skill workflow necesita poder elegir entre acciones y a veces aplicar varias en secuencia. Granularidad permite además que `diagnose_filters` se use de forma standalone (auditoría sin modificar nada).

**Reglas críticas para `remap_fields`**:
1. Recorrer **todos** los lugares donde aparece `[X]`:
   - `<column name='[X]'>` en datasources
   - `<rows>`, `<cols>` en worksheets
   - `<datasource-dependencies>/column[@name='[X]']`
   - `<filter column='...[X]'>`
   - Fórmulas dentro de `<calculation formula='...'>`
   - `<encoding field='[X]'>`
2. **No tocar** referencias a parámetros: `[Parameters].[X]`
3. Preservar IDs generados (`Calculation_416653341754003462`) — no son nombres de campo
4. Tracking: devolver reporte de cada reemplazo (cuántas ocurrencias por campo)

**Validación estructural pre-save** (`validate_structural`):
1. XML sintácticamente válido (parsea sin excepción)
2. Cada `<datasource>` referenciada en sheets existe en `<datasources>`
3. Cada `[campo]` usado en sheets existe como `<column>` o calc field
4. Fórmulas de calc fields no tienen refs huérfanas
5. Parámetros referenciados existen

**Estado**: 🔨 Pendiente Fase 2

---

### 5.6 `composer.py` — Composición multi-source de dashboards *[Fase 3 — pendiente]*

**Propósito**: Ensamblar un workbook nuevo, **multi-tab**, a partir de **N sheets seleccionados desde M workbooks fuente distintos**, apuntando a una datasource elegida. Resuelve dependencias transitivas, mergea calc fields y parámetros con manejo de conflictos, aplica cross-version indicator mapping y produce un layout válido publicable.

Caso de uso guía: el "Public Shared Insight Dashboard" descrito en §2.2 — 2 tabs con ~12 charts en total, fuentes en 5-8 templates de survey.

**Modelo de input**:

```python
@dataclass
class ChartSelection:
    workbook_id: str          # entry_id del catálogo (cloud_xxx o local_xxx)
    sheet_name: str           # nombre del sheet en el workbook fuente
    target_tab: str           # tab destino en el workbook compuesto
    title_override: str | None = None    # rename opcional ("Indicator Overview")
    supporting_line: str | None = None   # texto narrativo bajo el chart
    transformations: list[Transform] = field(default_factory=list)
    # transforms ej.: "convert_to_percentage", "drop_filter:organization"

@dataclass
class CompositionSpec:
    name: str                            # "Public Shared Insight"
    target_datasource_id: str            # LUID de la datasource destino
    target_project_id: str
    tabs: list[Tab]                      # ordered list of tabs
    public_filters_whitelist: list[str]  # solo estos filtros sobreviven
    indicator_mapping_overrides: dict    # cross-version overrides
    percentage_mode: bool = False        # reescribe SUM/COUNT → % cuando aplica

@dataclass
class Tab:
    name: str                            # "Where are we now?"
    layout: str                          # "grid_2col" | "stacked" | "free"
    selections: list[ChartSelection]
```

**Algoritmo (extendido)**:

```
1. INPUT: CompositionSpec

2. Indicator mapping resolution:
   a. Cargar indicator-cross-version-map.md + survey_comparison.xlsx
   b. Para cada workbook fuente, derivar su versión survey
      (matching por dbname / caption del datasource)
   c. Aplicar overrides de la spec

3. Dependency resolution (por chart):
   Para cada ChartSelection:
      a. Localizar workbook en catálogo, descargar si solo Cloud
      b. Parse → ParsedWorkbook
      c. Encontrar el sheet
      d. Resolver transitivamente:
         - calc_fields_directos = sheet.calc_fields_used
         - calc_fields_transitivos = closure de calc_fields_directos
                                     siguiendo depends_on en cada uno
         - params = params usados por sheet + por calc_fields transitivos
         - filters = sheet.filters (excluyendo los no-whitelisted)
         - context_filters = sheet.context_filters (idem)
      e. Devolver ChartBundle con todo lo necesario

4. Cross-source merge:
   a. Calc fields:
      - Agrupar por (caption_normalizado, fórmula_normalizada)
      - Si caption+fórmula igual → 1 sola copia, dedup
      - Si caption igual pero fórmula distinta → renombrar
        con sufijo de source (qty_surveys__BrayWicklow)
      - Reasignar IDs Calculation_xxx para evitar colisiones
   b. Parámetros:
      - Match por (caption, datatype, param_domain_type, allowed_values)
      - Match → 1 copia; conflicto → renombrar con sufijo
   c. Aliases: mismo tratamiento
   d. Reporte: lista de cada decisión (kept/merged/renamed)

5. Cross-version indicator remap (capa específica survey program):
   a. Para cada chart, identificar campos referenciados
   b. Para cada campo, consultar IndicatorMapping:
      - Si es un indicador con codename estable → target = mapping[codename][target_version]
      - Si es demográfico → fallback a field_matcher con la datasource destino
      - Si no resuelve → marcar como "needs_user_input"
   c. Aplicar remap a TODOS los lugares (rows, cols, filters, encodings, fórmulas)

6. Transform pipeline (por chart):
   - percentage_mode=True → reescribir SUM([X]) / COUNT(*) o calc 
     fields equivalentes para devolver porcentajes
   - drop_filter:X → remover esos filtros del sheet
   - rename:title → cambiar título visible
   - inject_supporting_line → text zone en el dashboard, atado al chart

7. Public filters layer:
   a. Eliminar filtros del workbook que NO estén en public_filters_whitelist
   b. Validar que cada filtro whitelisted existe en la datasource destino;
      si no, advertir (probablemente el filtro no aplica a esta versión)

8. Build new .twb:
   - <datasources>
       - target datasource (sqlproxy con dbname + LUID)
       - Parameters datasource con params mergeados
   - <column> declarations con todos los calc fields mergeados
   - <worksheets> con los N sheets remapeados
   - <dashboards>
       - 1 dashboard por Tab definido en la spec
       - layout según Tab.layout (grid_2col / stacked / free)
       - text zones para supporting_lines
       - filter zone con los public filters

9. Validación estructural (workbook_editor.validate_structural)
   - XML parseable
   - Refs cruzadas consistentes
   - Calc fields sin refs huérfanas
   - Cada dashboard zone referencia un sheet existente
   - Cross-tab: ningún sheet duplicado entre tabs sin querer

10. Backup (si overwrite) + Publish + report final
```

**Estructura del reporte de composición**:

```python
@dataclass
class CompositionReport:
    workbook_id: str
    name: str
    tabs_built: int
    charts_included: int
    calc_fields: {"kept": int, "merged_dedup": int, "renamed": list[str]}
    parameters:  {"kept": int, "merged_dedup": int, "renamed": list[str]}
    indicators_remapped: {"by_mapping_table": int, "by_field_matcher": int, "unresolved": list[str]}
    filters_dropped: list[str]      # por blacklist o no-whitelisted
    transformations_applied: dict   # {"percentage_mode": 5, "drop_filter:org": 7}
    warnings: list[str]
    structural_issues: list[Issue]
```

**Casos borde a manejar**:
- Sheets que dependen de parámetros que el usuario quiere descartar (cuando no aplican al contexto público) → el composer puede sustituir la ref del parámetro por su `current_value` hardcodeado, dejando una "vista simplificada".
- Calc fields con LOD expressions complejas (FIXED [dim1], [dim2]: ...) → preservar tal cual, no intentar simplificar.
- Fórmulas que referencian otros calc fields cuyos IDs cambiaron en el merge → recorrer las fórmulas y reescribir referencias después del merge.
- Field types incompatibles entre fuentes origen y destino (ej: campo era integer en source, real en target) → detectar y reportar, no romper silenciosamente.
- Charts cuyo indicador conceptual no existe en la datasource destino (ej: el RegionA template usa "podiatry checks" que solo aplica a Older Adults) → marcar como `unresolved`, ofrecer al usuario: (a) descartar el chart, (b) elegir un indicador alternativo, (c) abortar.
- Maps: pueden depender de geocodificación a nivel de Tableau que no se trae automáticamente con el sheet — flagear como caso especial y pedir al usuario que verifique tras la primera publish.

**Interfaz pública**:

```python
class DashboardComposer:
    def __init__(catalog: WorkbookCatalog, 
                 client: TableauClient,
                 indicator_mapping: IndicatorMapping)
    
    def resolve_dependencies(spec: CompositionSpec) -> list[ChartBundle]
    def merge_dependencies(bundles: list[ChartBundle]) -> MergedDeps
    def apply_indicator_remap(merged: MergedDeps, target_ds_fields: list[str]) -> RemappedDeps
    def build_twb(spec: CompositionSpec, remapped: RemappedDeps, output_path: str) -> str
    def compose(spec: CompositionSpec, dry_run: bool = False) -> CompositionReport
```

**Estado**: 🔨 Pendiente Fase 3

---

### 5.7 `server.py` — MCP Server (entry point)

**Propósito**: Exponer las capacidades del sistema como herramientas MCP que Claude puede invocar.

**Herramientas de Fase 1 (implementadas)**:

| Tool | Descripción |
|---|---|
| `site_info` | Info del sitio conectado |
| `list_projects` | Proyectos del sitio |
| `list_workbooks` | Workbooks publicados |
| `list_datasources` | Datasources publicadas |
| `get_datasource_fields` | Campos de una datasource (Metadata API) |
| `refresh_datasource` | Dispara refresh |
| `check_refresh_job` | Estado de un job |
| `refresh_and_wait` | Refresh sincrónico con timeout |
| `download_workbook` | Descarga .twb localmente |
| `parse_workbook` | Análisis estructural completo |
| `workbook_summary` | Análisis rápido |
| `compare_datasources` | Mapping con scores |
| `build_catalog` | Indexa todo |
| `catalog_stats` | Estadísticas del índice |
| `list_indexed_workbooks` | Lista entradas del catálogo |
| `search_catalog` | Búsqueda por descripción + filtros |
| `get_workbook_details` | Detalle de una entrada |
| `backup_workbook` | Copia con sufijo de fecha |

**Herramientas de Fase 2 (pendientes)**:
- `swap_datasource_in_workbook`
- `remap_workbook_fields`
- `validate_workbook_xml`
- `republish_workbook`
- `clone_and_remap` (high-level: combina los anteriores)

**Herramientas de Fase 3 (pendientes)**:
- `fix_filter_context`
- `change_field_aggregation`
- `update_calc_field`
- `diagnose_workbook` (escaneo de problemas comunes)
- `compose_dashboard`

**Estado**: ✅ Fase 1 implementada

---

## 6. Workflows clave (sequence diagrams en prosa)

### 6.1 Workflow: Refresh simple

```
Usuario: "refrescá la datasource de Survey RegionA"
  ↓
Claude consulta Skill → workflows/refresh.md
  ↓
Claude llama: list_datasources()
  ↓ filtra por nombre que contenga "RegionA"
Claude llama: refresh_and_wait(datasource_id="...", timeout_seconds=600)
  ↓ espera resultado
Claude responde: "Listo, terminó en 47s sin errores"
```

### 6.2 Workflow: Clone + Remap *[Fase 2]*

```
Usuario: "cloná el dashboard Region A para la encuesta RegionB"
  ↓
Skill → workflows/clone-remap.md
  ↓
Claude: search_catalog("RegionA")
  ↓ encuentra workbook
Claude: list_datasources()
  ↓ encuentra "Survey-RegionB"
Claude: compare_datasources(old_bray_id, new_east_lothian_id)
  ↓ recibe mapping con 92% auto, 5 dudosos, 1 sin match
Claude muestra al usuario los 5 dudosos con candidatos y los samples de datos
  ↓ usuario confirma/corrige
Claude: backup_workbook(bray_workbook_id)   # backup safety
  ↓
Claude: clone_and_remap(
    source_workbook_id, target_datasource_id, field_mapping,
    new_name="Survey - RegionB"
)
  ↓ esto internamente:
  ↓   - download workbook
  ↓   - swap_datasource
  ↓   - remap_fields (incluye calc fields + filtros + params)
  ↓   - validate_structural
  ↓   - publish con nuevo nombre + project_id
Claude: validate post-publish (REST API check)
  ↓
Claude responde: "Listo, publicado en proyecto X. 92 campos remapeados,
                  5 confirmados manualmente, 0 errores estructurales."
```

### 6.3 Workflow: Bug fix *[Fase 3]*

El bug fix **no es un script lineal**. El usuario describe un síntoma, y Claude tiene que diagnosticar antes de actuar. Una misma descripción ("el filtro no funciona", "los porcentajes están raros") puede mapear a cualquiera de las familias de bugs de §2.1. El workflow es un árbol diagnóstico con ramas múltiples; las correcciones varían tanto que no tienen forma fija.

**Estructura general**:

```
Usuario describe el síntoma (puede ser vago)
  ↓
[FASE 1 — Localizar]
  Claude: search_catalog → identifica workbook
  Claude: get_workbook_details + (si es necesario) parse_workbook
  Claude pregunta al usuario si no queda claro qué sheet/dashboard,
  o si el síntoma es ambiguo
  ↓
[FASE 2 — Diagnosticar (ningún caso asume el bug)]
  Según pistas del síntoma, correr una o varias de:
    - diagnose_filters(sheet_or_all)
    - diagnose_calc_fields()
    - diagnose_aggregations()
    - diagnose_datasource_health()
    - diagnose_parameters()
    - diagnose_dashboard_layout()
  Cada uno devuelve lista de Issues con hipótesis y fix_actions sugeridas.
  ↓
[FASE 3 — Triage]
  Claude presenta al usuario:
    - Issues encontrados, ordenados por severidad y plausibilidad
    - Para cada uno: hipótesis en lenguaje natural + acciones posibles
  Usuario confirma cuál(es) fixear, o pide más info, o descarta hipótesis.
  ↓
[FASE 4 — Aplicar fix (rama según el caso)]
  backup_workbook (siempre, antes de tocar)
  Ejecutar las fix_actions confirmadas:
    - puede ser 1 sola acción granular
    - puede ser una secuencia (ej: set_filter_context + set_filter_scope)
    - puede involucrar varios módulos (filter + calc field + parámetro)
  ↓
[FASE 5 — Validar + Republicar]
  validate_structural
  Si hay issues estructurales nuevos → rollback automático, reportar
  Sino → republish_workbook
  ↓
[FASE 6 — Confirmar con el usuario]
  Reportar qué cambió, en qué líneas, con diff humano-legible
  Sugerir cómo verificar visualmente (qué chart abrir primero)
```

**Ejemplo A — Síntoma vago "el filtro de organización no filtra bien"**:

```
Claude: parse_workbook + diagnose_filters(sheet=None)
  ↓ encuentra 3 issues sobre el filtro 'organization':
     1. SCOPE_TOO_NARROW en sheets "Indicator Overview" y "Map" 
        (filtro existe en "Base line" pero no se propaga)
     2. NOT_IN_CONTEXT_BUT_NEEDS_TO_BE en "BvA.AreaOfResidence"
        (el sheet usa LOD FIXED por dimensión)
     3. STALE_VALUES en "Base line" 
        (filtro hardcodea "Org A", "Org B" pero la datasource solo tiene "Org A")
  ↓
Claude muestra al usuario los 3 issues con hipótesis y plausibilidad,
y pregunta cuál(es) cree que es el problema reportado, o si quiere fixearlos todos.
  ↓
Usuario: "el del scope, los otros sheets no filtran"
  ↓
Claude:
  backup_workbook
  promote_filter_to_dashboard(dashboard="Indicator", 
                              sheet="Base line", 
                              filter_field="organization")
  validate_structural → ok
  republish
  "Listo. El filtro de organization ahora aplica a los 4 sheets del 
   dashboard. De paso detecté 2 issues más en ese filtro: valores 
   obsoletos en 'Base line' y un sheet que necesita context filter 
   por su LOD. ¿Querés que los toque también?"
```

**Ejemplo B — Síntoma "los porcentajes están raros"** (no necesariamente es un bug de filtros):

```
Claude: diagnose_aggregations() + diagnose_calc_fields()
  ↓ encuentra:
     - 1 calc field con SUM([householdMonthlyIncome]) cuando el campo ya 
       viene pre-agregado por familia → grano doble
     - 1 ratio (% Red) calculado como SUM(red_count)/COUNT(*) cuando 
       debería ser un AVG sobre un calc field por-fila
  ↓
Claude muestra hipótesis y propone fixes:
  - update_calc_field_formula para el primer caso
  - ajustar el ratio (recalc o cambiar agregación) para el segundo
  ↓
Usuario confirma → backup → apply → validate → republish → report.
```

**Ejemplo C — Síntoma "el dashboard no abre / muestra error"**:

```
Claude: diagnose_datasource_health() + diagnose_dashboard_layout()
  ↓ encuentra:
     - El workbook referencia datasource sqlproxy.LUID_VIEJO que ya no 
       existe en Cloud (la datasource fue republicada con LUID nuevo)
     - 2 dashboard zones apuntan a sheets renombrados
  ↓
Claude propone:
  swap_datasource(old=LUID_VIEJO, new=LUID_NUEVO)
  rebind_dashboard_zone para los 2 zones
  ↓
Confirmar → fix → validate → republish.
```

**Clave del diseño**: Claude **no asume** que el síntoma describe el bug que el usuario cree que es. Diagnostica con varias herramientas, presenta múltiples hipótesis ordenadas por plausibilidad, y deja que el usuario elija. La librería de fixes es granular justamente para que la rama "Aplicar fix" sea distinta según el caso.

### 6.4 Workflow: Composición multi-source *[Fase 3]*

**Modalidad chica** (ad-hoc, 2-5 charts):

```
Usuario: "armame un dashboard con:
         - el chart de evolución mensual del dashboard RegionA
         - el mapa de Score del dashboard RegionB
         - la tabla de prioridades del dashboard Northumbria
         todo apuntando a Survey-NewProject"
  ↓
Skill → workflows/compose-dashboard.md
  ↓
Claude: search_catalog para cada uno
  ↓ resuelve los tres entries
Claude: get_workbook_details para cada uno → identifica sheets exactos
  ↓
Claude: compose_dashboard(spec=CompositionSpec(
    name="Compose - Snapshot Q3",
    target_datasource_id="...",
    tabs=[Tab(name="Snapshot", layout="grid_2col", selections=[...])],
    public_filters_whitelist=[],
))
  ↓ dependency resolution + merge + indicator remap + publish
Claude reporta: "3 sheets, 18 calc fields (15 kept + 2 dedup + 1 renamed),
                1 parámetro mergeado, 0 indicadores sin resolver."
```

**Modalidad grande — caso "Public Shared Insight"**:

```
Usuario: "armá el Public Shared Insight Dashboard según las notas
         de commissioning, apuntando a Survey-PublicConsolidated"
  ↓
Skill → workflows/compose-dashboard.md → modo "from spec file"
  ↓
Claude lee:
  - commissioning_notes.docx
  - survey_comparison.xlsx (cross-version mapping)
  ↓
Claude: search_catalog para localizar workbooks fuente de cada chart
  ↓ resuelve los 5-8 templates necesarios (Survey-V2, CFN, RegionA, Older Adults,
    Easy-Read variant, Young Adults, COVID-19)
  ↓
Claude construye el CompositionSpec:
  - tabs=[Tab("Where are we now?", ...), Tab("What has changed?", ...)]
  - public_filters_whitelist=[survey_number, ethnic_group, age, 
                              area_of_residence, gender, education]
  - percentage_mode=True
  - drop filters: organization, project
  ↓
Claude: compose_dashboard(spec, dry_run=True)
  ↓ ejecuta dependency resolution + merge SIN publicar
  ↓ devuelve CompositionReport preview
  ↓
Claude muestra al usuario:
  - 12 charts a ensamblar (7 + 5)
  - 64 calc fields totales (42 kept + 15 dedup + 7 renamed)
  - 5 indicadores que necesitan decisión manual (no mapeados)
  - 4 filtros descartados
  - 0 issues estructurales
  ↓
Usuario revisa los 5 unresolved + confirma
  ↓
Claude: compose_dashboard(spec, dry_run=False)
  ↓ build .twb + validate_structural + backup_workbook si overwrite
  ↓ publish_workbook
  ↓ verifica via REST API que apareció
  ↓
Claude responde: "Listo. 'Public Shared Insight' publicado en
                  proyecto Public. 2 tabs, 12 charts. URL: ..."
```

**Validación post-build manual** (sugerida al usuario): abrir en Tableau Desktop antes del go-live público para verificar que (a) los maps cargan con su geocoding, (b) los porcentajes se ven sensatos, (c) el Human Agency Score (si activado) está bien.

---

## 7. Stack tecnológico

| Capa | Tecnología | Justificación |
|---|---|---|
| Lenguaje | Python 3.10+ | Stack existente, ecosistema Tableau (TSC) maduro |
| MCP framework | `mcp` (FastMCP) | Estándar de Anthropic, stdio transport |
| Tableau REST/Metadata | `tableauserverclient` (TSC) | Cliente oficial de Tableau |
| XML parsing | `xml.etree.ElementTree` (stdlib) | Suficiente para .twb, sin dependencias extra |
| Config | `python-dotenv` | `.env` para credenciales |
| Fuzzy matching | `difflib.SequenceMatcher` (stdlib) | No requiere instalar libs externas tipo rapidfuzz |
| Persistencia catálogo | JSON | Legible, diff-able, sin DB local que mantener |
| Auth | Personal Access Token (PAT) | Recomendación oficial Tableau Cloud |

**Por qué no usar otras opciones**:
- `tableaudocumentapi` (deprecated 2022): mantener forks no oficiales no es sostenible
- DB embebida (SQLite) para catálogo: overkill para 20-100 entradas, JSON alcanza
- `lxml` en lugar de `ElementTree`: lxml es más rápido pero introduce dep compilada; no es necesario para volúmenes reales

---

## 8. Plan de implementación por fases

### Fase 1 — Foundation ✅ COMPLETADO

**Entregado**:
- `tableau_client.py`, `workbook_parser.py`, `field_matcher.py`, `catalog.py`, `server.py` (18 tools)
- `skill/SKILL.md`, `skill/workflows/refresh.md`, `skill/references/twb-xml-anatomy.md`
- README, .env.example, requirements.txt

**Validado contra**: workbook real Survey-RegionA-Sample (99 sheets, 12 dashboards, 86 calc fields, 4 parámetros) — parser captura todo correctamente.

**Tiempo estimado real**: 1 sesión de trabajo

---

### Fase 2 — Clone + Remap 🔨 PENDIENTE

**Entregables**:
- `workbook_editor.py` con:
  - `swap_datasource(old_name, new_id, new_caption)`
  - `remap_fields(mapping: dict)`
  - `validate_structural() -> list[str]`
  - `save(output_path)`
- Tools nuevas en `server.py`:
  - `swap_datasource_in_workbook`
  - `remap_workbook_fields`
  - `validate_workbook_xml`
  - `republish_workbook`
  - `clone_and_remap` (high-level)
- Skill: `skill/workflows/clone-remap.md`
- Refinamiento del parser: desempaquetar prefijos de agregación (`pcto:sum:Field:qk:3` → `Field`)

**Criterio de aceptación**:
- Tomar Survey-RegionA, apuntarlo a una datasource de prueba con 1-2 nombres distintos, republicarlo, abrirlo en Tableau Desktop sin errores.
- Reporte de qué se cambió antes de publish.
- Backup automático generado.

**Tiempo estimado**: 3-5 días de trabajo

---

### Fase 3 — Bug Fix + Composición 🔨 PENDIENTE

**Entregables**:
- `workbook_editor.py` extendido con:
  - **API granular de filtros** (ver §5.5 para signatures completas):
    - `diagnose_filters(sheet_name=None)` — detecta los 10 tipos de FilterIssue (§10.4)
    - `set_filter_context`, `set_filter_scope`, `change_filter_type`, `reorder_filters`
    - `remove_stale_filter_values`, `fix_filter_action`, `promote_filter_to_dashboard`
  - **API granular para otras familias**:
    - `diagnose_calc_fields`, `update_calc_field_formula`, `fix_lod_dimension`
    - `diagnose_aggregations`, `change_aggregation`
    - `diagnose_datasource_health` (LUIDs huérfanos, refs rotas)
    - `diagnose_parameters`, `fix_parameter_value`, `add_parameter_allowed_value`
    - `diagnose_dashboard_layout`, `rebind_dashboard_zone`, `remove_orphan_zone`
  - `diagnose_workbook() -> list[Issue]` — meta-tool que orquesta los diagnose_* anteriores y los devuelve unificados, ordenados por severidad
- `composer.py` (módulo nuevo) con:
  - `IndicatorMapping` registry (carga desde `survey_comparison.xlsx` + overrides)
  - `resolve_dependencies(spec, parsed_wbs) -> list[ChartBundle]` (transitiva)
  - `merge_dependencies(bundles) -> MergedDeps` (con conflict handling para calc fields, params, aliases)
  - `apply_indicator_remap(merged, target_ds_fields) -> RemappedDeps`
  - `apply_transforms(remapped, spec) -> TransformedDeps` (percentage_mode, filter whitelist, etc.)
  - `build_twb(spec, transformed, output_path) -> str`
  - `compose(spec, dry_run) -> CompositionReport`
- Tools nuevas en `server.py` (todas envuelven la API granular del editor):
  - **Diagnóstico**:
    - `diagnose_workbook` (orquestador), `diagnose_filters`, `diagnose_calc_fields`, `diagnose_aggregations`, `diagnose_datasource_health`, `diagnose_parameters`, `diagnose_dashboard_layout`
  - **Fixes de filtros** (mapean 1:1 a operaciones del editor):
    - `set_filter_context`, `set_filter_scope`, `change_filter_type`, `reorder_filters`, `remove_stale_filter_values`, `fix_filter_action`, `promote_filter_to_dashboard`
  - **Fixes de calc fields / agregación / parámetros / layout**:
    - `update_calc_field_formula`, `fix_lod_dimension`, `change_field_aggregation`, `fix_parameter_value`, `add_parameter_allowed_value`, `rebind_dashboard_zone`, `remove_orphan_zone`
  - **Composición**:
    - `compose_dashboard` (one-shot, modo chico)
  - `preview_composition` (modo dry-run que devuelve el CompositionReport sin publicar)
  - `load_indicator_mapping` (recarga desde el Excel cross-version)
- Skills: 
  - `skill/workflows/bug-fix.md`
  - `skill/workflows/compose-dashboard.md` (cubre modalidad chica + grande)
- References:
  - `skill/references/common-bugs-catalog.md`
  - `skill/references/indicator-cross-version-map.md` (versión Markdown del Excel para que la skill la consulte rápido sin tener que abrir el .xlsx en cada turn)

**Criterio de aceptación**:
- Bug fix:
  - `diagnose_workbook` corre sobre el .twb de RegionA y produce > 0 issues coherentes con problemas verificables manualmente.
  - Para cada **familia** (filtros, calc fields, agregación, datasource, parámetros, layout): demostrar al menos un caso end-to-end (diagnose → triage con hipótesis → aplicar fix granular → validate → republish → confirmar diff).
  - En particular para **filtros**: cubrir como mínimo 3 de los 10 tipos de la taxonomía de §10.4 (recomendado: NOT_IN_CONTEXT, SCOPE_TOO_NARROW, STALE_VALUES), mostrando que el workflow elige rama correcta sin forzar la respuesta.
- Composición (modalidad chica): tomar 3 sheets de 3 workbooks distintos, componerlos en un nuevo dashboard funcional contra una datasource de prueba, sin issues estructurales.
- Composición (modalidad grande): ensamblar el Public Shared Insight Dashboard end-to-end: 12 charts de 5-8 workbooks fuente, 2 tabs, publicado en Cloud, abierto en Tableau Desktop sin errores. Reporte de composición debe tener < 5 indicadores sin resolver y 0 issues estructurales.

**Tiempo estimado**: 5-8 días de trabajo (más que la estimación previa porque la composición grande agrega el IndicatorMapping registry, el dry-run preview, el percentage_mode y el filter whitelist).

---

## 9. Estrategia de field mapping (detallada)

Específica para el contexto survey program. Esta es la lógica que ejecuta `compare_datasources`:

### 9.1 Pipeline

```
old_fields, new_fields
    ↓
for each old in old_fields:
    1. Exact match? → confidence 1.00
    2. Case-insensitive? → confidence 0.98
    3. Normalize (snake↔camel) y comparar? → confidence 0.92
    4. Fuzzy con SequenceMatcher → score
       - score ≥ 0.95 → auto-aplicable
       - 0.75 ≤ score < 0.95 → needs_confirmation, mostrar candidatos
       - score < 0.75 → no_match
    5. (Opcional) Refinar con samples de datos:
       - Obtener 10 valores de old desde Metadata API o samples
       - Obtener 10 valores de cada candidato
       - Jaccard similarity → boost de confidence si overlap > 50%
```

### 9.2 Heurísticas específicas para survey program

- **Indicadores**: los nombres técnicos son estables. Si `old` ∈ {income, stableIncome, accessToCredit, ..., los 50 indicadores}, esperar exact match. Si no hay exact, **flagear como anomalía**: probablemente alguien renombró un indicador que no debería renombrarse.
- **Familias (demográficos)**: alta variabilidad. housingSituation puede ser HousingSituation, housing_situation, vivienda, etc. Aquí el fuzzy + samples es esencial.
- **IDs y fechas**: family_code, survey_id, survey_date, survey_number — esperar exact siempre.

### 9.3 Diccionario incremental

`skill/references/semaforo-field-dictionary.md` (a construir):

```markdown
## Indicadores (estables, exact match esperado)
- income = "Money to live on"
- stableIncome = "Stable Income"
- accessToCredit = "Bank account confidence"
[...]

## Familias - Variaciones conocidas
- householdMonthlyIncome ↔ Household_Monthly_Income ↔ ingreso_mensual_hogar
- housingSituation ↔ HousingSituation ↔ situacion_vivienda
[...]
```

Cada vez que aparezca una variación nueva durante un clone+remap, agregarla al diccionario para que la próxima vez sea auto-match.

---

## 10. Estrategia de manipulación de XML

### 10.1 Cuándo cada operación es segura

| Operación | Riesgo | Lugares a tocar |
|---|---|---|
| Cambiar `caption` de datasource | Bajo | Solo en `<datasource>` y `<datasource caption='...'>` refs |
| Cambiar `dbname` y `name` de datasource | Medio | Todos los `name='sqlproxy.X'` refs (sheets, dashboards) |
| Renombrar campo `[X]` → `[Y]` | Alto | column declarations, rows/cols, datasource-dependencies, filtros, fórmulas de calc fields, encodings |
| Cambiar fórmula de calc field | Bajo | Solo el atributo `formula` del `<calculation>` |
| Agregar context a un filtro | Bajo | Cambiar `filter-group='1'` a `'2'` |
| Cambiar scope de un filtro (worksheet → dashboard) | Medio | Cambiar `apply-to-worksheets` del `<filter>` + posible necesidad de duplicar el filtro a otros sheets si la versión XML no soporta apply-to global |
| Cambiar tipo de filtro (categorical → range, etc.) | Medio | Reescribir el `<filter class='...'>` con la estructura interna correcta (members vs range vs wildcard) |
| Remover valores obsoletos del filtro | Bajo | Quitar `<member>` huérfanos; preservar resto del filtro |
| Reordenar filtros | Bajo | Reordenar elementos `<filter>` dentro del `<view>` |
| Reparar filter action de dashboard | Medio | Modificar `<action>` con sus `<source-zones>` y `<target-zones>` |
| Rebind de zone a otro sheet | Medio | Cambiar `<view><worksheet name='X'/></view>` dentro de `<zone>` |
| Cambiar agregación en sheet | Bajo | Modificar `SUM([X])` → `AVG([X])` en rows/cols |
| Cambiar dimensión de un LOD FIXED | Medio | Reescribir `{FIXED [dim1]: ...}` → `{FIXED [dim2]: ...}` en la fórmula del calc field |
| Fijar valor de parámetro | Bajo | Cambiar `value=` del `<column param-domain-type='...'>` |

### 10.2 Validación estructural pre-publish

Validador que corre antes de cada `republish_workbook`:

```python
def validate_structural(parsed: ParsedWorkbook) -> list[Issue]:
    issues = []

    # 1. XML válido (ya garantizado si parseó)

    # 2. Datasource refs consistentes
    ds_names = {d.name for d in parsed.datasources}
    for sheet in parsed.sheets:
        for ds_ref in sheet.datasources_used:
            if not any(d.caption == ds_ref or d.name == ds_ref for d in parsed.datasources):
                issues.append(Issue("missing_datasource", sheet.name, ds_ref))

    # 3. Field refs existen
    for sheet in parsed.sheets:
        valid_fields = collect_valid_fields_for_sheet(sheet, parsed)
        for field in sheet.fields_used:
            if field not in valid_fields and not is_calc_field(field, parsed):
                issues.append(Issue("orphan_field", sheet.name, field))

    # 4. Calc field formulas no tienen refs huérfanas
    for cf in parsed.calc_fields:
        for dep in cf.depends_on_fields:
            if dep not in valid_fields and not is_calc_field(dep, parsed):
                issues.append(Issue("orphan_calc_ref", cf.name, dep))

    # 5. Parámetros referenciados existen
    param_names = {p.caption for p in parsed.parameters}
    for cf in parsed.calc_fields:
        for p_ref in cf.depends_on_params:
            if p_ref not in param_names:
                issues.append(Issue("orphan_param_ref", cf.name, p_ref))

    return issues
```

### 10.3 Validación post-publish (liviana)

Solo verificar que la REST API respondió 200 al `publish_workbook` y que el workbook aparece en `list_workbooks`. Esto cacha el 80% de errores con mínima latencia.

### 10.4 Taxonomía de bugs de filtros y sus fixes

Esta tabla es la base operativa de `diagnose_filters` y de las acciones expuestas por `workbook_editor.py`. No es exhaustiva, pero cubre lo que aparece con más frecuencia en workbooks reales.

| # | Tipo (FilterIssueType) | Síntoma típico | Pista en el XML | Fix recomendado |
|---|---|---|---|---|
| 1 | NOT_IN_CONTEXT_BUT_NEEDS_TO_BE | Los porcentajes/LODs no respetan el filtro | `<filter ... filter-group='1'>` en sheet con `{FIXED ...}` o cálculos % | `set_filter_context(sheet, field, in_context=True)` |
| 2 | IN_CONTEXT_BUT_SHOULDNT_BE | Filtro corre antes que otros sin razón, performance pobre | `filter-group='2'` sin LOD/FIXED ni necesidad de pre-filtrar | `set_filter_context(sheet, field, in_context=False)` |
| 3 | SCOPE_TOO_NARROW | El filtro aplica solo al sheet activo cuando debería filtrar todo el dashboard | `apply-to-worksheets="only-this"` o ausente; otros sheets del dashboard usan misma ds | `set_filter_scope(..., apply_to="all_using_this_ds")` o `promote_filter_to_dashboard` |
| 4 | SCOPE_TOO_BROAD | Filtro afecta sheets que no deberían filtrarse | `apply-to-worksheets="all"` con sheets que tienen lógica propia | `set_filter_scope(..., apply_to="specific", target_sheets=[...])` |
| 5 | TYPE_MISMATCH | Filtro no captura todos los valores esperados | `<filter class='categorical'>` sobre `datatype='real'`, etc. | `change_filter_type(..., new_type=...)` apropiado al campo |
| 6 | STALE_VALUES | Filtro vacío o le faltan opciones en UI | `<groupfilter>` con `<member>` que ya no existe en la datasource | `remove_stale_filter_values` (consulta datasource via Metadata API) |
| 7 | ORDER_DEPENDENCY | Resultados cambian si se aplica un filtro antes de otro | Múltiples filtros sin context, orden depende del XML order | `reorder_filters(sheet, new_order=[...])` |
| 8 | ACTION_BROKEN | Click en una marca no filtra el sheet destino | `<action>` apunta a `<worksheet name='X'>` que ya no existe | `fix_filter_action(...)` con sheets/fields actualizados |
| 9 | NOT_APPLIED_AT_DASHBOARD_LEVEL | Usuario espera filtro global pero solo está en un sheet | Filter solo aparece en un `<worksheet>`, no a nivel dashboard | `promote_filter_to_dashboard` |
| 10 | CROSS_DS_MISCONFIGURED | Filtro de una datasource no afecta sheets de otra relacionada | `<filter>` sin `class='all-using-related'` cuando debería | `set_filter_scope(..., apply_to="all_using_related")` |

**Heurísticas que usa `diagnose_filters`**:

- Si un sheet tiene `<calculation>` con `{FIXED ...}` y un filtro NO está en context filter para una de esas dimensiones → flag tipo 1.
- Si dos o más sheets del mismo dashboard usan la misma datasource y un filtro existe solo en uno de ellos → flag tipo 3.
- Si los valores hardcodeados del filtro (`<member value='X'>`) no aparecen en `get_datasource_fields(...)` de esa columna → flag tipo 6.
- Si un `<action>` referencia un sheet name que no existe en `<worksheets>` → flag tipo 8.

**Reglas de actuación**:

1. **Diagnóstico ≠ acción**: `diagnose_filters` solo *propone*. No modifica nada.
2. **Severidad calibrada**: un STALE_VALUES en un filtro inactivo es info; un ACTION_BROKEN en un dashboard usado es error.
3. **Hipótesis con confianza explícita**: si dos hipótesis explican el mismo síntoma, mostrar ambas en orden de plausibilidad — no forzar una decisión.
4. **Fix idempotente**: aplicar el mismo fix dos veces no debería romper. La validación estructural detecta inconsistencias incluso si el fix se aplicó parcialmente.

---

## 11. Configuración y deployment

### 11.1 Variables de entorno

```bash
TABLEAU_SERVER_URL=https://prod-useast-a.online.tableau.com
TABLEAU_SITE_NAME=your-site-slug
TABLEAU_PAT_NAME=mcp-workflow
TABLEAU_PAT_VALUE=<secret-token>
TABLEAU_LOCAL_FOLDER=C:/Users/<you>/Documents/Tableau
TABLEAU_CATALOG_PATH=~/.tableau-workflow/catalog.json
```

### 11.2 Claude Desktop config

`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tableau-workflow": {
      "command": "python",
      "args": ["C:/proyectos/tableau-workflow/server.py"]
    }
  }
}
```

### 11.3 Claude Code config

`~/.claude/config.toml`:

```toml
[mcp_servers.tableau-workflow]
command = "python"
args = ["/ruta/a/tableau-workflow/server.py"]
```

### 11.4 Cowork

Cowork detecta automáticamente los MCP configurados en Claude Desktop si está instalado en la misma máquina. Sino, replicar la config de Desktop.

### 11.5 Primer arranque

```bash
# 1. Instalar deps
pip install -r requirements.txt

# 2. Crear PAT en Tableau Cloud
#    Avatar → My Account Settings → Personal Access Tokens

# 3. Llenar .env

# 4. Probar conexión
python -c "from tableau_client import TableauClient; print(TableauClient().site_info())"

# 5. Build catálogo (primera vez tarda 5-15min para 50-100 workbooks)
#    Hacerlo desde Claude: "buildea el catálogo de Tableau"
```

---

## 12. Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| PAT expirado (15 días sin uso) | Alta | Bajo | Mensaje claro de error 401 + instrucción de regenerar |
| Formato .twb cambia entre versiones de Tableau | Media | Alto | Probar con workbooks generados desde la versión local. Si rompe, detectar versión y ajustar |
| Calc fields complejos con LOD anidados fallan al remapear | Media | Medio | Validación estructural + reporte de cuáles calc fields no se pudieron remapear automáticamente, pedirle al usuario que revise |
| Conflictos de nombres en composición | Alta | Bajo | Renaming automático con sufijo + reporte |
| Indexar Cloud completo es lento (5-15 min) | Alta | Bajo | Permitir indexar por proyecto (subset); cachear y solo refrescar lo modificado |
| Metadata API requiere permisos Creator | Media | Bajo | Fallback: parsear directamente el .twb descargado |
| Publish corrupto si XML inválido | Baja | Alto | Validación estructural pre-publish obligatoria |
| Tableau Desktop bloquea el .twb si está abierto | Baja | Bajo | Detectar lock y avisar al usuario |
| Diagnose_filters falsos positivos | Media | Bajo | Hipótesis se muestran con plausibilidad explícita; ningún fix se aplica sin confirmación del usuario |
| Fix granular aplicado en orden equivocado por workflow | Baja | Medio | Cada `fix_*` es idempotente; validación estructural post-fix detecta inconsistencias antes del republish |

---

## 13. Estrategia de testing

### 13.1 Tests unitarios (a implementar)

```
tests/
  test_parser.py
    - test_parses_real_twbx (con fixture del RegionA .twbx)
    - test_extracts_all_calc_fields
    - test_extracts_dependencies_from_formulas
    - test_handles_twbx_with_extract

  test_field_matcher.py
    - test_exact_match
    - test_case_insensitive_match
    - test_normalized_match
    - test_fuzzy_match_with_candidates
    - test_no_match_threshold
    - test_sample_refinement

  test_catalog.py
    - test_index_local_folder
    - test_search_by_query
    - test_search_by_filters
    - test_persistence_roundtrip

  test_editor.py  [Fase 2]
    - test_swap_datasource
    - test_remap_simple_field
    - test_remap_in_calc_field_formula
    - test_preserves_parameter_refs
    - test_validate_structural_catches_orphan_field

  test_filter_diagnose.py  [Fase 3]
    - test_detects_not_in_context_when_lod_present
    - test_detects_scope_too_narrow_in_dashboard
    - test_detects_stale_values_via_metadata_api
    - test_detects_broken_action
    - test_no_false_positive_on_intentional_local_filter

  test_filter_fixes.py  [Fase 3]
    - test_set_filter_context_idempotent
    - test_set_filter_scope_preserves_others
    - test_promote_filter_to_dashboard_updates_xml_correctly
    - test_remove_stale_values_keeps_valid
    - test_change_filter_type_preserves_state

  test_composer.py  [Fase 3]
    - test_resolve_dependencies_transitive
    - test_merge_dedupes_identical_calc_fields
    - test_merge_renames_conflicting_calc_fields
    - test_indicator_remap_uses_cross_version_map
    - test_dry_run_returns_report_without_publishing
```

### 13.2 Integration tests

- Test contra Tableau Cloud de desarrollo (no producción de your organization)
- Validar full cycle: parse → edit → validate → publish → reload → verify

### 13.3 Manual smoke tests

Tras cada release de fase:
1. Refresh de 1 datasource (Fase 1)
2. Clone+remap de un workbook simple a otra datasource (Fase 2)
3. Bug fix multi-familia (Fase 3): correr `diagnose_workbook` sobre un workbook real, elegir 3 issues de distintas familias, fixearlos uno por uno con el workflow de §6.3 — confirmar que el árbol diagnóstico funciona sin asumir respuestas.
4. Composición modalidad chica: 3 sheets de 3 workbooks en un nuevo dashboard (Fase 3)
5. Composición modalidad grande: Public Shared Insight end-to-end con dry_run + publish (Fase 3)

---

## 14. Estructura final del proyecto

```
tableau-workflow/
├── server.py                                    # MCP entry point
├── tableau_client.py                            # REST + Metadata API
├── workbook_parser.py                           # Parsea .twb / .twbx
├── workbook_editor.py        [Fase 2-3]         # Modifica .twb (API granular)
├── field_matcher.py                             # Compara datasources
├── catalog.py                                   # Índice persistente
├── composer.py               [Fase 3]           # Composición multi-workbook
├── requirements.txt
├── .env.example
├── .env                                         # (no commitear)
├── README.md
├── SDD.md                                       # este documento
├── tests/                    [a implementar]
│   ├── fixtures/
│   │   └── sample-workbook.twbx              # workbook real para tests
│   ├── test_parser.py
│   ├── test_field_matcher.py
│   ├── test_catalog.py
│   ├── test_editor.py        [Fase 2]
│   ├── test_filter_diagnose.py [Fase 3]
│   ├── test_filter_fixes.py    [Fase 3]
│   └── test_composer.py        [Fase 3]
└── skill/
    ├── SKILL.md
    ├── workflows/
    │   ├── refresh.md                            ✅
    │   ├── clone-remap.md            [Fase 2]
    │   ├── bug-fix.md                [Fase 3]
    │   └── compose-dashboard.md      [Fase 3]
    └── references/
        ├── twb-xml-anatomy.md                    ✅
        ├── filter-bug-taxonomy.md    [Fase 3]
        ├── common-bugs-catalog.md    [Fase 3]
        ├── semaforo-field-dictionary.md [incremental]
        └── indicator-cross-version-map.md [Fase 3]
```

---

## 15. Glosario

| Término | Definición |
|---|---|
| **.twb** | Archivo XML que define un workbook de Tableau (estructura, sin datos) |
| **.twbx** | Archivo zip que contiene un .twb + datos extract + recursos |
| **Published Datasource** | Datasource publicada en Tableau Cloud/Server, reutilizable por múltiples workbooks |
| **PAT** | Personal Access Token, mecanismo de auth de Tableau (expira tras 15 días sin uso) |
| **sqlproxy** | Connection class en el XML que indica conexión a una Published Datasource |
| **LUID** | Locally Unique Identifier — el ID de una datasource en Tableau Cloud |
| **Calc field** | Campo calculado definido por una fórmula en Tableau |
| **LOD** | Level of Detail expressions: `{FIXED ...}`, `{INCLUDE ...}`, `{EXCLUDE ...}` |
| **Filter context** | Filtro que aplica antes de otras agregaciones (filter-group='2' en XML) |
| **Filter scope** | Conjunto de sheets a los que aplica un filtro (atributo `apply-to-worksheets`) |
| **Filter action** | Interacción de dashboard donde clickear una marca filtra otros sheets |
| **FilterIssue** | Modelo de bug de filtro detectado por `diagnose_filters`; ver taxonomía §10.4 |
| **survey program / Indicator** | Metodología de your organization para medir pobreza multidimensional |
| **MCP** | Model Context Protocol — estándar de Anthropic para exponer herramientas a Claude |
| **Skill** | Carpeta con SKILL.md que guía a Claude en cómo abordar tipos de tareas |
| **TSC** | Tableau Server Client, librería Python oficial |

---

## 16. Decisiones de diseño registradas

| ID | Decisión | Justificación | Fecha |
|---|---|---|---|
| D-001 | Skill + MCP (no uno solo) | MCP da operaciones, Skill da consistencia de workflow | 2026-05-18 |
| D-002 | No generar dashboards complejos desde cero | Workbooks reales tienen 80+ calc fields, generación pura no es realista | 2026-05-18 |
| D-003 | Backup solo en overwrites a Cloud | Balance entre seguridad y ruido en el workspace | 2026-05-18 |
| D-004 | Field matching en 5 niveles + samples | Nombres técnicos del survey program son estables, pero demográficos varían | 2026-05-18 |
| D-005 | Catálogo en JSON, no DB | Volumen bajo (20-100 wb), JSON es legible y diff-able | 2026-05-18 |
| D-006 | Validación estructural pre + liviana post | Cacha errores con mínima latencia | 2026-05-18 |
| D-007 | Modo mixto de confirmación de mapeos | Alta confianza auto, dudosos con samples al usuario | 2026-05-18 |
| D-008 | Indexado completo al inicio (no lazy) | Volumen permite full rebuild en 5-15 min | 2026-05-18 |
| D-009 | Composición preserva calc fields con renaming en conflictos | Más útil que rechazar la operación | 2026-05-18 |
| D-010 | Persistir catálogo en ~/.tableau-workflow/ | Convención de configuración del usuario | 2026-05-18 |
| D-011 | Composición soporta N sheets de M workbooks (no limitada a 2-3) y output multi-tab | El caso real "Public Shared Insight" requiere 12 charts de 5-8 fuentes en 2 tabs. Limitar a 2-3 obliga a múltiples corridas y pierde el merge cross-source | 2026-05-18 |
| D-012 | IndicatorMapping registry dedicado para cross-version survey program | Los demográficos varían entre versiones de survey y el field_matcher solo no alcanza; tener una tabla canónica (alimentada por survey_comparison.xlsx) evita ambigüedades | 2026-05-18 |
| D-013 | Dry-run obligatorio en composiciones grandes | Una composición de 12 charts es alto-impacto; el preview del CompositionReport permite catchear unresolved indicators y conflictos antes de publicar | 2026-05-18 |
| D-014 | Filter whitelist (no blacklist) para variantes públicas | Más seguro: cualquier filtro nuevo de un template fuente queda fuera por default en lugar de filtrarse al dashboard público sin querer | 2026-05-18 |
| D-015 | API granular de fixes en lugar de funciones monolíticas | Los bugs de filtros tienen ≥10 variantes (taxonomía §10.4); una sola `fix_filter_context` no modela las decisiones reales. Granularidad permite que el workflow elija acciones según el caso y combine fixes sin reescribir lógica | 2026-05-18 |
| D-016 | Bug fix es árbol diagnóstico, no script lineal | El usuario describe síntomas, no causas. Diagnosticar primero, presentar hipótesis ordenadas por plausibilidad, dejar que el usuario elija — evita falsos arreglos y refleja cómo se resuelven los bugs reales | 2026-05-18 |
| D-017 | `diagnose_*` separadas de los `fix_*` | Permite auditorías read-only y mantiene la responsabilidad simple: el diagnosticador propone, el editor ejecuta | 2026-05-18 |

---

## 17. Próximos pasos inmediatos

1. **Validar Fase 1 con setup real**: instalar localmente, configurar `.env`, correr `build_catalog` con un proyecto chico de Cloud (ej: limitar a 5 workbooks de prueba).
2. **Detectar problemas reales del parser**: si los prefijos de agregación `pcto:sum:...` molestan en alguna búsqueda del catálogo, fix.
3. **Arrancar Fase 2**:
   - Empezar por `workbook_editor.swap_datasource` (la más simple)
   - Luego `remap_fields` con tests sobre el .twb de RegionA
   - Después `validate_structural`
   - Por último el tool high-level `clone_and_remap`
4. **Skill playbook de clone-remap**: escribir en paralelo con la implementación.
5. **Pre-trabajo para Fase 3 — Bug Fix**:
   - Implementar `diagnose_filters` primero (es el más diverso y se usa también en clone+remap como validación pre-publish).
   - Construir `references/filter-bug-taxonomy.md` (Markdown derivado de §10.4 con ejemplos concretos de los 10 tipos sobre workbooks reales).
   - Implementar los fixes granulares de filtros antes que las otras familias — son los más frecuentes.
   - Validar contra el .twb de RegionA: correr `diagnose_workbook` y revisar manualmente que los issues detectados sean reales (calibrar heurísticas y severidad).
6. **Pre-trabajo para Fase 3 — Composición**:
   - Convertir `survey_comparison.xlsx` (la sheet `Comparison`) a `skill/references/indicator-cross-version-map.md` con formato consultable por la skill. Un fila por codename, columnas por versión.
   - Identificar los workbooks fuente en Cloud para cada chart del Public Shared Insight Dashboard (mapping chart → (workbook_id, sheet_name)) y dejarlo como apéndice del SDD o como spec file aparte (ej. `compositions/public-shared-insight.yaml`).
   - Definir el formato del spec file (YAML o JSON) que `compose_dashboard` consumirá en modalidad grande, para no construir el `CompositionSpec` a mano cada vez.

---

*Fin del SDD v1.2*
