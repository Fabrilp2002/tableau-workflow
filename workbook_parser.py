"""
workbook_parser.py — Parser de archivos .twb (XML de Tableau).

Convierte un .twb en una estructura Python navegable que captura:
- Datasources y sus conexiones
- Parámetros con sus valores permitidos
- Calculated fields con sus fórmulas y dependencias
- Worksheets y los campos/calc fields/parámetros que usan
- Dashboards y sus zones
- Referencias cruzadas (qué sheet usa qué calc field, etc.)

Acepta tanto .twb (XML) como .twbx (zip que contiene un .twb).
"""

import re
import zipfile
import tempfile
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from typing import Optional


# Regex para extraer referencias [Campo] de fórmulas
FIELD_REF_RE = re.compile(r"\[([^\[\]]+)\]")


@dataclass
class FieldRef:
    name: str
    datasource: Optional[str] = None


@dataclass
class Datasource:
    name: str
    caption: str
    inline: bool
    connection_class: Optional[str] = None
    connection_dbname: Optional[str] = None
    connection_server: Optional[str] = None
    is_published: bool = False  # True si class=sqlproxy


@dataclass
class Parameter:
    name: str
    caption: str
    datatype: str
    param_domain_type: str  # 'list' | 'range' | 'any'
    current_value: Optional[str] = None
    allowed_values: list = field(default_factory=list)


@dataclass
class CalcField:
    name: str  # nombre interno (con brackets quitados)
    caption: str
    datasource: str  # caption de la datasource padre
    formula: str
    role: Optional[str] = None  # dimension | measure
    datatype: Optional[str] = None
    depends_on_fields: list = field(default_factory=list)  # campos referenciados en la fórmula
    depends_on_params: list = field(default_factory=list)  # parámetros referenciados


@dataclass
class Sheet:
    name: str
    datasources_used: list = field(default_factory=list)
    fields_used: list = field(default_factory=list)  # field refs en rows/cols/encodings
    calc_fields_used: list = field(default_factory=list)  # calc field names referenciados
    parameters_used: list = field(default_factory=list)
    filters: list = field(default_factory=list)  # nombres de campos filtrados
    context_filters: list = field(default_factory=list)
    mark_type: Optional[str] = None  # bar | line | text | ...


@dataclass
class Dashboard:
    name: str
    sheets_used: list = field(default_factory=list)
    zone_count: int = 0


@dataclass
class ParsedWorkbook:
    twb_path: str
    version: str
    source_build: str
    datasources: list = field(default_factory=list)
    parameters: list = field(default_factory=list)
    calc_fields: list = field(default_factory=list)
    sheets: list = field(default_factory=list)
    dashboards: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "twb_path": self.twb_path,
            "version": self.version,
            "source_build": self.source_build,
            "summary": {
                "datasources": len(self.datasources),
                "parameters": len(self.parameters),
                "calc_fields": len(self.calc_fields),
                "sheets": len(self.sheets),
                "dashboards": len(self.dashboards),
            },
            "datasources": [asdict(d) for d in self.datasources],
            "parameters": [asdict(p) for p in self.parameters],
            "calc_fields": [asdict(c) for c in self.calc_fields],
            "sheets": [asdict(s) for s in self.sheets],
            "dashboards": [asdict(d) for d in self.dashboards],
        }

    def all_field_references(self) -> set:
        """Devuelve el conjunto de todos los nombres de campo referenciados en el workbook."""
        refs = set()
        for s in self.sheets:
            refs.update(s.fields_used)
        for c in self.calc_fields:
            refs.update(c.depends_on_fields)
        return refs

    def find_sheet(self, name: str) -> Optional[Sheet]:
        return next((s for s in self.sheets if s.name == name), None)

    def find_calc_field(self, name: str) -> Optional[CalcField]:
        return next((c for c in self.calc_fields if c.name == name or c.caption == name), None)


class WorkbookParser:
    """Parser de archivos .twb / .twbx."""

    def parse(self, path: str) -> ParsedWorkbook:
        twb_path = self._ensure_twb(path)
        tree = ET.parse(twb_path)
        root = tree.getroot()

        result = ParsedWorkbook(
            twb_path=path,
            version=root.get("version", "?"),
            source_build=root.get("source-build", "?"),
        )

        ds_caption_by_name = {}

        # ── Datasources ──
        for ds_el in root.findall("datasources/datasource"):
            ds = self._parse_datasource(ds_el)
            ds_caption_by_name[ds.name] = ds.caption
            result.datasources.append(ds)

            # Parámetros viven en la datasource especial "Parameters"
            if ds.name == "Parameters":
                for col in ds_el.findall("column"):
                    p = self._parse_parameter(col)
                    if p:
                        result.parameters.append(p)
            else:
                # Calculated fields
                for col in ds_el.findall("column"):
                    calc = col.find("calculation")
                    if calc is not None and calc.get("class") == "tableau":
                        cf = self._parse_calc_field(col, calc, ds.caption)
                        result.calc_fields.append(cf)

        # ── Worksheets ──
        for ws_el in root.findall("worksheets/worksheet"):
            sheet = self._parse_sheet(ws_el, ds_caption_by_name)
            result.sheets.append(sheet)

        # ── Dashboards ──
        for db_el in root.findall("dashboards/dashboard"):
            dashboard = self._parse_dashboard(db_el)
            result.dashboards.append(dashboard)

        return result

    # ─────────────────────────────────────────
    #  Helpers internos
    # ─────────────────────────────────────────

    def _ensure_twb(self, path: str) -> str:
        """
        Si es .twbx, extrae el .twb a un tmpdir y retorna esa path.

        Seguridad: valida el nombre interno del zip contra zip-slip
        (paths absolutos, .., separadores raros, drive letters en Windows).
        """
        if path.lower().endswith(".twb"):
            return path
        if not path.lower().endswith(".twbx"):
            raise ValueError(f"Extensión no soportada: {path}")

        tmpdir = tempfile.mkdtemp(prefix="twb_extract_")
        with zipfile.ZipFile(path, "r") as zf:
            twb_name = next(
                (n for n in zf.namelist() if n.lower().endswith(".twb")), None
            )
            if not twb_name:
                raise ValueError(f"No se encontró .twb dentro de {path}")

            # Normalize and reject any traversal attempts
            normalized = twb_name.replace("\\", "/")
            if (
                normalized.startswith("/")
                or normalized.startswith("..")
                or ".." in normalized.split("/")
                or (len(normalized) >= 2 and normalized[1] == ":")
            ):
                raise ValueError(f"Nombre interno inseguro en .twbx: {twb_name!r}")

            zf.extract(twb_name, tmpdir)
            extracted = os.path.realpath(os.path.join(tmpdir, twb_name))
            tmpdir_real = os.path.realpath(tmpdir)
            if not (
                extracted == tmpdir_real
                or extracted.startswith(tmpdir_real + os.sep)
            ):
                raise ValueError(
                    f"Zip slip detectado: el archivo se extrajo fuera de tmpdir "
                    f"({extracted!r} vs {tmpdir_real!r})"
                )
            return extracted

    def _parse_datasource(self, ds_el) -> Datasource:
        name = ds_el.get("name", "?")
        caption = ds_el.get("caption", name)
        inline = ds_el.get("inline", "false").lower() == "true"

        ds = Datasource(name=name, caption=caption, inline=inline)
        # Primera conexión (suele ser una sola para published datasources)
        conn = ds_el.find("connection")
        if conn is not None:
            ds.connection_class = conn.get("class")
            ds.connection_dbname = conn.get("dbname")
            ds.connection_server = conn.get("server")
            ds.is_published = ds.connection_class == "sqlproxy"
        # Caso de federated connections (más de una)
        for fc in ds_el.findall(".//named-connection"):
            inner = fc.find("connection")
            if inner is not None and ds.connection_class is None:
                ds.connection_class = inner.get("class")
                ds.connection_dbname = inner.get("dbname")
                ds.connection_server = inner.get("server")
                ds.is_published = ds.connection_class == "sqlproxy"
                break
        return ds

    def _parse_parameter(self, col) -> Optional[Parameter]:
        param_type = col.get("param-domain-type")
        if not param_type:
            return None
        p = Parameter(
            name=col.get("name", "?").strip("[]"),
            caption=col.get("caption", col.get("name", "?")),
            datatype=col.get("datatype", "?"),
            param_domain_type=param_type,
            current_value=col.get("value"),
        )
        # allowed values en <aliases> o <members>
        for member in col.findall(".//member"):
            v = member.get("value")
            if v is not None:
                p.allowed_values.append(v)
        return p

    def _parse_calc_field(self, col, calc, ds_caption: str) -> CalcField:
        name = col.get("name", "?").strip("[]")
        caption = col.get("caption", name)
        formula = calc.get("formula", "")
        cf = CalcField(
            name=name,
            caption=caption,
            datasource=ds_caption,
            formula=formula,
            role=col.get("role"),
            datatype=col.get("datatype"),
        )
        # Extraer dependencias del formula
        refs = FIELD_REF_RE.findall(formula)
        for ref in refs:
            # Las refs a parámetros vienen como "Parameters].[NombreParam"
            if "Parameters]" in formula and ref.startswith("Parameters") is False:
                # detección simple: parámetros aparecen como [Parameters].[Foo]
                if f"[Parameters].[{ref}]" in formula:
                    cf.depends_on_params.append(ref)
                    continue
            cf.depends_on_fields.append(ref)
        return cf

    def _parse_sheet(self, ws_el, ds_caption_by_name: dict) -> Sheet:
        sheet = Sheet(name=ws_el.get("name", "?"))

        # Datasources usadas en esta vista
        for ds_ref in ws_el.findall(".//view/datasources/datasource"):
            cap = ds_ref.get("caption") or ds_caption_by_name.get(ds_ref.get("name", ""), "")
            if cap and cap not in sheet.datasources_used:
                sheet.datasources_used.append(cap)

        # Fields referenciados en rows/cols
        for tag in ["rows", "cols"]:
            for el in ws_el.findall(f".//{tag}"):
                if el.text:
                    sheet.fields_used.extend(FIELD_REF_RE.findall(el.text))

        # Datasource-dependencies (declaración explícita)
        for dep_col in ws_el.findall(".//datasource-dependencies/column"):
            field_name = dep_col.get("name", "").strip("[]")
            if field_name and field_name not in sheet.fields_used:
                sheet.fields_used.append(field_name)

        # Filtros
        for f in ws_el.findall(".//filter"):
            col_attr = f.get("column", "")
            field_name = FIELD_REF_RE.findall(col_attr)
            if field_name:
                sheet.filters.append(field_name[0])
            # Context filter detection
            if f.get("class") == "categorical" and f.get("filter-group") == "2":
                if field_name:
                    sheet.context_filters.append(field_name[0])

        # Marcas
        mark = ws_el.find(".//mark")
        if mark is not None:
            sheet.mark_type = mark.get("class", "").lower()

        # Eliminar duplicados manteniendo orden
        sheet.fields_used = list(dict.fromkeys(sheet.fields_used))
        sheet.filters = list(dict.fromkeys(sheet.filters))
        sheet.context_filters = list(dict.fromkeys(sheet.context_filters))

        return sheet

    def _parse_dashboard(self, db_el) -> Dashboard:
        dashboard = Dashboard(name=db_el.get("name", "?"))
        for zone in db_el.findall(".//zone"):
            if zone.get("type") == "view":
                ws = zone.find(".//worksheet")
                if ws is not None:
                    sheet_name = ws.get("name")
                    if sheet_name and sheet_name not in dashboard.sheets_used:
                        dashboard.sheets_used.append(sheet_name)
            dashboard.zone_count += 1
        return dashboard
