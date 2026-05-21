"""
server.py — MCP Server principal del Tableau Workflow Assistant.

Fase 1 (este archivo): refresh + discovery + catálogo + análisis de workbooks.
Fase 2 (próxima iteración): clone+remap.
Fase 3 (próxima iteración): bug fixing + composición.

Las herramientas se exponen vía FastMCP usando stdio transport,
compatible con Claude Desktop y Claude Code.
"""

import os
import json
import tempfile
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from tableau_client import TableauClient
from workbook_parser import WorkbookParser
from field_matcher import FieldMatcher
from catalog import WorkbookCatalog

load_dotenv()

mcp = FastMCP("Tableau Workflow Assistant")

CATALOG_PATH = os.environ.get(
    "TABLEAU_CATALOG_PATH",
    os.path.expanduser("~/.tableau-workflow/catalog.json"),
)
LOCAL_TWB_FOLDER = os.environ.get("TABLEAU_LOCAL_FOLDER", "")

# ─────────────────────────────────────────
#  SEGURIDAD — path allow-list
# ─────────────────────────────────────────
#
# Los tools que reciben un path como argumento (parse_workbook, workbook_summary,
# download_workbook(save_dir), build_catalog(local_folder)) confían en strings
# que vienen del LLM. Un workbook prompt-injected podría pedirle a Claude que
# llame con un path arbitrario tipo "C:/Users/.../credentials" o "C:/Windows/".
#
# Para mitigarlo, restringimos los paths a un set de "roots permitidos":
#   - TABLEAU_LOCAL_FOLDER (carpeta de .twb del usuario)
#   - El tempdir del sistema (donde descargamos workbooks de Cloud)
#   - Una carpeta opcional adicional via TABLEAU_EXTRA_ALLOWED_PATHS
#     (separada por ';' en Windows o ':' en Unix)
#
# Si un tool recibe un path fuera de estos roots, devuelve error sin tocar disco.

def _allowed_roots() -> list[Path]:
    roots: list[Path] = []
    if LOCAL_TWB_FOLDER:
        roots.append(Path(LOCAL_TWB_FOLDER).resolve())
    roots.append(Path(tempfile.gettempdir()).resolve())
    extra = os.environ.get("TABLEAU_EXTRA_ALLOWED_PATHS", "").strip()
    if extra:
        sep = ";" if os.name == "nt" else ":"
        for r in extra.split(sep):
            r = r.strip()
            if r:
                roots.append(Path(r).resolve())
    return roots


def _validate_path(p: str, must_exist: bool = True) -> tuple[bool, str]:
    """
    Verifica que `p` esté dentro de un root permitido. Devuelve (ok, msg).
    Si must_exist=True, también valida que el path exista en disco.
    Pensado para usarse desde los tools del MCP.
    """
    if not p:
        return False, "Path vacío"
    try:
        target = Path(p).resolve()
    except (OSError, ValueError) as e:
        return False, f"Path inválido: {e}"

    if must_exist and not target.exists():
        return False, f"Path no existe: {target}"

    roots = _allowed_roots()
    if not roots:
        return False, (
            "No hay roots permitidos configurados. Definí TABLEAU_LOCAL_FOLDER "
            "o TABLEAU_EXTRA_ALLOWED_PATHS en tu .env."
        )

    for root in roots:
        try:
            target.relative_to(root)
            return True, ""
        except ValueError:
            continue

    return False, (
        f"Path {target} está fuera de los roots permitidos. "
        f"Roots configurados: {[str(r) for r in roots]}. "
        f"Si querés permitir este path, agregalo a TABLEAU_EXTRA_ALLOWED_PATHS."
    )


def _client() -> TableauClient:
    return TableauClient()


def _catalog() -> WorkbookCatalog:
    return WorkbookCatalog(CATALOG_PATH)


def _jdump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


# ─────────────────────────────────────────
#  CONECTIVIDAD + LISTADOS
# ─────────────────────────────────────────


@mcp.tool()
def site_info() -> str:
    """Info del sitio de Tableau Cloud conectado. Útil para verificar credenciales."""
    return _jdump(_client().site_info())


@mcp.tool()
def list_projects() -> str:
    """Lista proyectos/carpetas del sitio (paginación completa)."""
    return _jdump(_client().list_projects())


@mcp.tool()
def list_workbooks(project_id: str = "") -> str:
    """Lista workbooks publicados. Opcionalmente filtra por project_id."""
    return _jdump(_client().list_workbooks(project_id=project_id or None))


@mcp.tool()
def list_datasources(project_id: str = "") -> str:
    """Lista datasources publicadas. Opcionalmente filtra por project_id."""
    return _jdump(_client().list_datasources(project_id=project_id or None))


@mcp.tool()
def get_datasource_fields(datasource_id: str) -> str:
    """
    Lista los campos de una datasource publicada (vía Metadata API).
    Retorna nombre técnico, datatype, role (dimension/measure).
    """
    return _jdump(_client().get_datasource_fields(datasource_id))


# ─────────────────────────────────────────
#  REFRESH
# ─────────────────────────────────────────


@mcp.tool()
def refresh_datasource(datasource_id: str) -> str:
    """Dispara refresh de una datasource. Retorna job_id para monitorear."""
    return _jdump(_client().refresh_datasource(datasource_id))


@mcp.tool()
def check_refresh_job(job_id: str) -> str:
    """Consulta estado de un job (refresh u otro). Retorna 'running' o finish code."""
    return _jdump(_client().check_job(job_id))


@mcp.tool()
def refresh_and_wait(datasource_id: str, timeout_seconds: int = 600) -> str:
    """
    Dispara refresh y espera hasta que termine o se cumpla el timeout.
    Útil cuando querés ejecutar refresh y confirmar éxito antes de seguir.
    """
    return _jdump(_client().refresh_and_wait(datasource_id, timeout_seconds))


# ─────────────────────────────────────────
#  WORKBOOK INSPECTION
# ─────────────────────────────────────────


@mcp.tool()
def download_workbook(workbook_id: str, save_dir: str = "") -> str:
    """
    Descarga un workbook de Tableau Cloud. Retorna la path local.
    Por default sin incluir el extract (más liviano).

    Seguridad: si se pasa save_dir, debe estar dentro de un root permitido
    (ver _allowed_roots). Si no se pasa, se usa un tempdir del sistema.
    """
    if save_dir:
        ok, msg = _validate_path(save_dir, must_exist=True)
        if not ok:
            return _jdump({"error": f"save_dir rechazado: {msg}"})
    path = _client().download_workbook(workbook_id, save_dir=save_dir or None)
    return _jdump({"local_path": path, "size_kb": os.path.getsize(path) // 1024})


@mcp.tool()
def download_datasource(
    datasource_id: str,
    save_dir: str = "",
    include_extract: bool = False,
) -> str:
    """
    Descarga una datasource publicada de Tableau Cloud. Retorna la path local.
    Por default sin incluir el extract (más liviano para edición).

    Seguridad: si se pasa save_dir, debe estar dentro de un root permitido.
    Si no se pasa, se usa un tempdir del sistema.
    """
    if save_dir:
        ok, msg = _validate_path(save_dir, must_exist=True)
        if not ok:
            return _jdump({"error": f"save_dir rechazado: {msg}"})
    path = _client().download_datasource(
        datasource_id,
        save_dir=save_dir or None,
        include_extract=include_extract,
    )
    return _jdump({"local_path": path, "size_kb": os.path.getsize(path) // 1024})


@mcp.tool()
def publish_datasource(
    tds_path: str,
    project_id: str,
    name: str,
    mode: str = "overwrite",
    db_username: str = "",
    db_password: str = "",
    auto_extract: bool = True,
    extract_wait_seconds: int = 240,
) -> str:
    """
    Publica un .tds o .tdsx a Tableau Cloud.

    Por default convierte la datasource a EXTRACT automáticamente tras publicar
    (auto_extract=True). Esto hace que los workbooks que la usen publiquen
    10-30× más rápido, porque Tableau Cloud valida los sheets contra el .hyper
    local (no hace queries a la fuente live).

    Args:
        tds_path: path local al .tds (live) o .tdsx (con extract).
        project_id: LUID del proyecto destino en el sitio.
        name: nombre de la datasource publicada.
        mode: 'overwrite' (default), 'createnew', o 'append'.
        db_username: usuario de la BD para embeder (necesario para refresh
            automatizado de extracts).
        db_password: password de la BD. Si se pasa con db_username, las
            credenciales quedan embebidas cifradas en Tableau Cloud.
        auto_extract: si True (default), tras publicar dispara create_extract
            automáticamente. Convierte la DS de live a extract.
        extract_wait_seconds: tiempo máximo (segundos) a esperar la
            materialización del extract antes de devolver. 0 = no esperar.

    Seguridad: tds_path debe existir y estar dentro de un root permitido.
    """
    ok, msg = _validate_path(tds_path, must_exist=True)
    if not ok:
        return _jdump({"error": f"tds_path rechazado: {msg}"})
    result = _client().publish_datasource(
        tds_path=tds_path,
        project_id=project_id,
        name=name,
        mode=mode,
        db_username=db_username or None,
        db_password=db_password or None,
        auto_extract=auto_extract,
        extract_wait_seconds=extract_wait_seconds,
    )
    return _jdump(result)


@mcp.tool()
def create_extract_for_datasource(
    datasource_id: str,
    encrypt: bool = False,
    wait_seconds: int = 240,
) -> str:
    """
    Convierte una datasource publicada de modo live → extract.

    Útil cuando la datasource se publicó como live (sin auto_extract) y se
    quiere ahora habilitar extract refrescable.

    Args:
        datasource_id: LUID de la datasource publicada.
        encrypt: si True, el extract queda encriptado server-side.
        wait_seconds: tiempo máximo (segundos) a esperar la materialización
            del extract antes de devolver. 0 = no esperar.

    Retorna: status del job. Si has_extracts=True, la conversión completó.
    Si has_extracts=False con un job_id, el job sigue async.
    """
    result = _client().create_extract_for_datasource(
        datasource_id=datasource_id,
        encrypt=encrypt,
        wait_seconds=wait_seconds,
    )
    return _jdump(result)


@mcp.tool()
def parse_workbook(twb_path: str) -> str:
    """
    Parsea un .twb o .twbx local. Retorna estructura completa:
    datasources, parámetros, calc fields (con dependencias), sheets, dashboards.
    Acepta tanto Cloud (después de download_workbook) como local.

    Seguridad: twb_path debe estar dentro de un root permitido.
    """
    ok, msg = _validate_path(twb_path, must_exist=True)
    if not ok:
        return _jdump({"error": f"twb_path rechazado: {msg}"})
    parser = WorkbookParser()
    parsed = parser.parse(twb_path)
    return _jdump(parsed.to_dict())


@mcp.tool()
def workbook_summary(twb_path: str) -> str:
    """
    Versión rápida de parse_workbook: solo el summary numérico + estructura básica.

    Seguridad: twb_path debe estar dentro de un root permitido.
    """
    ok, msg = _validate_path(twb_path, must_exist=True)
    if not ok:
        return _jdump({"error": f"twb_path rechazado: {msg}"})
    parser = WorkbookParser()
    parsed = parser.parse(twb_path)
    return _jdump({
        "summary": parsed.to_dict()["summary"],
        "datasources": [{"caption": d.caption, "is_published": d.is_published} for d in parsed.datasources],
        "dashboards": [{"name": d.name, "sheets": d.sheets_used} for d in parsed.dashboards],
        "parameter_names": [p.caption for p in parsed.parameters],
    })


# ─────────────────────────────────────────
#  COMPARE DATASOURCES (clone+remap prep)
# ─────────────────────────────────────────


@mcp.tool()
def compare_datasources(old_datasource_id: str, new_datasource_id: str) -> str:
    """
    Compara campos de dos datasources publicadas y propone mapeo automático.
    Útil para preparar un clone+remap entre encuestas del survey program.

    Retorna:
    - matches: lista de [campo_viejo → campo_nuevo, confidence, método]
    - summary: cuántos son auto-aplicables, cuántos necesitan confirmación
    """
    client = _client()
    old = client.get_datasource_fields(old_datasource_id)
    new = client.get_datasource_fields(new_datasource_id)

    if "error" in old:
        return _jdump({"error": f"Old datasource: {old['error']}"})
    if "error" in new:
        return _jdump({"error": f"New datasource: {new['error']}"})

    old_names = [f["name"] for f in old["fields"]]
    new_names = [f["name"] for f in new["fields"]]

    matcher = FieldMatcher()
    matches = matcher.match(old_names, new_names)
    return _jdump({
        "old_datasource": old["datasource_name"],
        "new_datasource": new["datasource_name"],
        "summary": matcher.summarize(matches),
        "matches": [m.to_dict() for m in matches],
    })


# ─────────────────────────────────────────
#  CATÁLOGO
# ─────────────────────────────────────────


@mcp.tool()
def build_catalog(
    local_folder: str = "",
    project_id: str = "",
    max_workbooks: int = 0,
    force: bool = False,
) -> str:
    """
    Construye/reconstruye el catálogo indexando todos los workbooks.
    Por default usa la carpeta de TABLEAU_LOCAL_FOLDER (env var) + todo Cloud.

    - local_folder: opcional, override de la carpeta local.
    - project_id: opcional, limita el indexado de Cloud a un proyecto específico.
    - max_workbooks: opcional, limita cuántos workbooks indexar en esta corrida
      (útil para builds chicos que terminen dentro del timeout del cliente MCP;
      llamar repetidamente para completar el catálogo en chunks).
    - force: si True, vacía el catálogo y reindexa todo desde cero. Por default
      es incremental: workbooks ya indexados con el mismo updated_at se saltean.

    El catálogo se persiste cada 5 workbooks indexados, así un timeout del
    cliente MCP no descarta el progreso parcial.

    Seguridad: si se pasa local_folder, debe estar dentro de un root permitido.
    Si está vacío, se usa TABLEAU_LOCAL_FOLDER (que ya es un root permitido por
    construcción). Esto evita que un workbook prompt-injected dispare un escaneo
    de todo C:\\ o de carpetas con secretos.
    """
    cat = _catalog()
    client = _client()
    folder = local_folder or LOCAL_TWB_FOLDER or None
    if folder:
        ok, msg = _validate_path(folder, must_exist=True)
        if not ok:
            return _jdump({"error": f"local_folder rechazado: {msg}"})

    result = cat.full_rebuild(
        client=client,
        local_folder=folder,
        project_id=project_id or None,
        force=force,
        max_workbooks=max_workbooks,
    )
    result["catalog_path"] = CATALOG_PATH
    result["stats"] = cat.stats()
    return _jdump(result)


@mcp.tool()
def catalog_stats() -> str:
    """Estadísticas del catálogo actual (sin reconstruir)."""
    return _jdump(_catalog().stats())


@mcp.tool()
def list_indexed_workbooks() -> str:
    """Lista todos los workbooks en el catálogo con su info básica."""
    return _jdump(_catalog().list_entries())


@mcp.tool()
def search_catalog(
    query: str = "",
    workbook_filter: str = "",
    mark_type: str = "",
    source: str = "",
) -> str:
    """
    Busca charts/sheets en el catálogo por descripción + filtros opcionales.

    Args:
        query: descripción natural ej "tendencia mensual ingresos"
        workbook_filter: filtra por nombre de workbook
        mark_type: filtra por tipo de marca (bar, line, text, etc.)
        source: 'cloud' o 'local'
    """
    results = _catalog().search(
        query=query,
        workbook_filter=workbook_filter or None,
        mark_type=mark_type or None,
        source=source or None,
    )
    return _jdump({"count": len(results), "results": results[:30]})


@mcp.tool()
def get_workbook_details(catalog_entry_id: str) -> str:
    """Detalle completo de un workbook del catálogo (sheets, calc fields, params)."""
    entry = _catalog().get_entry(catalog_entry_id)
    if not entry:
        return _jdump({"error": f"Entry no encontrada: {catalog_entry_id}"})
    return _jdump(entry)


# ─────────────────────────────────────────
#  BACKUP
# ─────────────────────────────────────────


@mcp.tool()
def backup_workbook(workbook_id: str, confirm: bool = False) -> str:
    """
    Crea un backup del workbook en Cloud (copia con sufijo _backup_FECHA).
    Útil antes de operaciones destructivas tipo overwrite.

    Seguridad / defense-in-depth:
    - Requiere confirm=True para ejecutar. Esto previene que un prompt-injected
      workbook engañe a Claude para crear copias innecesarias o exfiltrar
      datos (incluye el extract real del workbook).
    - El workbook_id se valida como UUID antes de llamar la API.

    Si confirm=False (default), devuelve qué haría sin ejecutar.
    """
    from tableau_client import _validate_luid
    err = _validate_luid(workbook_id, "workbook_id")
    if err:
        return _jdump({"error": err})

    if not confirm:
        return _jdump({
            "preview": True,
            "would_create": f"backup de workbook {workbook_id} con sufijo _backup_YYYY-MM-DD",
            "note": "Llamar de nuevo con confirm=True para ejecutar.",
        })

    return _jdump(_client().backup_workbook(workbook_id))


if __name__ == "__main__":
    mcp.run()
