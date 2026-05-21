"""
catalog.py — Índice de todos los workbooks disponibles (Cloud + carpeta local).

Construye y persiste un catálogo en JSON con la "ficha técnica" de cada workbook:
sheets, charts (con dim/measure/mark_type), calc fields, parameters, datasources.

Permite buscar por descripción natural ("gráficos de tendencia mensual"),
filtrar por workbook, o listar dependencias para composición.
"""

import os
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional
from workbook_parser import WorkbookParser, ParsedWorkbook
from tableau_client import TableauClient


CATALOG_VERSION = "1.0"


class WorkbookCatalog:
    """Catálogo persistido en JSON con metadata de todos los workbooks."""

    def __init__(self, catalog_path: str):
        self.catalog_path = catalog_path
        self.data = self._load()
        self.parser = WorkbookParser()

    def _load(self) -> dict:
        if os.path.exists(self.catalog_path) and os.path.getsize(self.catalog_path) > 0:
            try:
                with open(self.catalog_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass  # archivo corrupto, empezar de cero
        return {
            "version": CATALOG_VERSION,
            "last_full_rebuild": None,
            "entries": {},  # {entry_id: {...metadata...}}
        }

    def save(self):
        os.makedirs(os.path.dirname(self.catalog_path) or ".", exist_ok=True)
        with open(self.catalog_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    # ─────────────────────────────────────────
    #  ENTRY BUILDING
    # ─────────────────────────────────────────

    def _entry_id(self, source: str, identifier: str) -> str:
        """ID estable para un workbook. source = 'cloud' | 'local'"""
        h = hashlib.md5(f"{source}:{identifier}".encode()).hexdigest()[:12]
        return f"{source}_{h}"

    def _build_entry(
        self,
        source: str,
        identifier: str,
        name: str,
        parsed: ParsedWorkbook,
        extra: Optional[dict] = None,
    ) -> dict:
        """Construye una entrada del catálogo a partir de un workbook parseado."""
        return {
            "id": self._entry_id(source, identifier),
            "source": source,  # 'cloud' o 'local'
            "identifier": identifier,  # workbook_id de Cloud o path local
            "name": name,
            "indexed_at": datetime.utcnow().isoformat(),
            "summary": parsed.to_dict()["summary"],
            "datasources": [
                {
                    "name": d.name,
                    "caption": d.caption,
                    "is_published": d.is_published,
                    "dbname": d.connection_dbname,
                }
                for d in parsed.datasources if d.name != "Parameters"
            ],
            "parameters": [
                {"name": p.name, "caption": p.caption, "type": p.param_domain_type}
                for p in parsed.parameters
            ],
            "calc_fields": [
                {
                    "name": c.name,
                    "caption": c.caption,
                    "depends_on": c.depends_on_fields[:10],  # truncate
                }
                for c in parsed.calc_fields
            ],
            "sheets": [
                {
                    "name": s.name,
                    "mark_type": s.mark_type,
                    "datasources": s.datasources_used,
                    "fields": s.fields_used[:10],  # truncate
                    "filters": s.filters,
                }
                for s in parsed.sheets
            ],
            "dashboards": [
                {"name": d.name, "sheets": d.sheets_used, "zones": d.zone_count}
                for d in parsed.dashboards
            ],
            "extra": extra or {},
        }

    # ─────────────────────────────────────────
    #  INDEXING
    # ─────────────────────────────────────────

    def index_local_folder(self, folder_path: str, recursive: bool = True) -> dict:
        """Indexa todos los .twb/.twbx en la carpeta."""
        folder = Path(folder_path)
        if not folder.exists():
            return {"error": f"Carpeta no encontrada: {folder_path}"}

        pattern = "**/*" if recursive else "*"
        twb_files = [
            p for p in folder.glob(pattern)
            if p.suffix.lower() in (".twb", ".twbx") and p.is_file()
        ]

        indexed = 0
        errors = []
        for path in twb_files:
            try:
                parsed = self.parser.parse(str(path))
                entry = self._build_entry(
                    source="local",
                    identifier=str(path),
                    name=path.stem,
                    parsed=parsed,
                    extra={"file_size": path.stat().st_size, "modified": path.stat().st_mtime},
                )
                self.data["entries"][entry["id"]] = entry
                indexed += 1
            except Exception as e:
                errors.append({"path": str(path), "error": str(e)})

        self.save()
        return {"indexed": indexed, "errors": errors, "total_files": len(twb_files)}

    def index_cloud(
        self,
        client: TableauClient,
        project_id: Optional[str] = None,
        skip_if_unchanged: bool = True,
        max_workbooks: int = 0,
        save_every: int = 5,
    ) -> dict:
        """
        Indexa workbooks de Tableau Cloud (descarga el .twb de cada uno).

        - skip_if_unchanged: si la entrada ya existe y `updated_at` no cambió,
          saltea el download+parse. Permite resumir builds interrumpidos.
        - max_workbooks: si > 0, limita cuántos procesa (útil para builds chicos
          que terminen dentro del timeout del cliente MCP).
        - save_every: persiste el catálogo cada N workbooks indexados, para que
          un timeout no descarte el progreso parcial.
        """
        workbooks = client.list_workbooks(project_id=project_id)
        if max_workbooks and max_workbooks > 0:
            workbooks = workbooks[:max_workbooks]

        indexed = 0
        skipped = 0
        errors = []
        for wb in workbooks:
            entry_id = self._entry_id("cloud", wb["id"])
            # Skip si el workbook no cambió desde la última indexación
            if skip_if_unchanged:
                existing = self.data["entries"].get(entry_id)
                if existing and existing.get("extra", {}).get("updated_at") == wb.get("updated_at"):
                    skipped += 1
                    continue
            try:
                path = client.download_workbook(wb["id"])
                parsed = self.parser.parse(path)
                entry = self._build_entry(
                    source="cloud",
                    identifier=wb["id"],
                    name=wb["name"],
                    parsed=parsed,
                    extra={
                        "project_id": wb["project_id"],
                        "project_name": wb["project_name"],
                        "content_url": wb["content_url"],
                        "webpage_url": wb["webpage_url"],
                        "updated_at": wb.get("updated_at"),
                    },
                )
                self.data["entries"][entry["id"]] = entry
                indexed += 1
                # Cleanup downloaded .twb (no necesitamos guardarlo)
                try:
                    os.unlink(path)
                except OSError:
                    pass
                # Persistir progreso incremental para que un timeout
                # del cliente MCP no descarte lo que ya se indexó.
                if save_every and indexed % save_every == 0:
                    self.save()
            except Exception as e:
                errors.append({"workbook": wb["name"], "error": str(e)})

        self.save()
        return {
            "indexed": indexed,
            "skipped": skipped,
            "errors": errors,
            "total_workbooks": len(workbooks),
        }

    def full_rebuild(
        self,
        client: Optional[TableauClient] = None,
        local_folder: Optional[str] = None,
        project_id: Optional[str] = None,
        force: bool = False,
        max_workbooks: int = 0,
    ) -> dict:
        """
        Build/rebuild del catálogo.

        - force=False (default): build incremental. Si el workbook no cambió
          desde la última indexación, se saltea. Permite resumir builds
          interrumpidos por timeouts del cliente MCP.
        - force=True: limpia el catálogo y reindexa todo desde cero.
        - project_id: limita la indexación cloud a un proyecto específico.
        - max_workbooks: limita cuántos workbooks indexar (útil para tests).
        """
        if force:
            self.data["entries"] = {}
        result = {"cloud": None, "local": None}
        if client:
            result["cloud"] = self.index_cloud(
                client,
                project_id=project_id,
                skip_if_unchanged=not force,
                max_workbooks=max_workbooks,
            )
        if local_folder:
            result["local"] = self.index_local_folder(local_folder)
        self.data["last_full_rebuild"] = datetime.utcnow().isoformat()
        self.save()
        return result

    # ─────────────────────────────────────────
    #  SEARCH
    # ─────────────────────────────────────────

    def search(
        self,
        query: str = "",
        workbook_filter: Optional[str] = None,
        mark_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> list[dict]:
        """
        Busca sheets/charts que matcheen una descripción + filtros opcionales.
        Devuelve una lista de matches con su contexto (workbook + sheet).
        """
        query_terms = [t.lower() for t in query.split() if t]
        results = []

        for entry in self.data["entries"].values():
            if source and entry["source"] != source:
                continue
            if workbook_filter and workbook_filter.lower() not in entry["name"].lower():
                continue

            for sheet in entry["sheets"]:
                if mark_type and sheet.get("mark_type") != mark_type:
                    continue
                # Score textual simple
                haystack = " ".join([
                    sheet["name"].lower(),
                    " ".join(sheet.get("fields", [])).lower(),
                    sheet.get("mark_type", "").lower(),
                    entry["name"].lower(),
                ])
                if query_terms:
                    score = sum(1 for t in query_terms if t in haystack)
                    if score == 0:
                        continue
                else:
                    score = 1

                results.append({
                    "score": score,
                    "workbook": entry["name"],
                    "workbook_id": entry["id"],
                    "source": entry["source"],
                    "sheet": sheet["name"],
                    "mark_type": sheet.get("mark_type"),
                    "fields": sheet.get("fields", []),
                })

        results.sort(key=lambda r: -r["score"])
        return results

    def get_entry(self, entry_id: str) -> Optional[dict]:
        return self.data["entries"].get(entry_id)

    def list_entries(self) -> list[dict]:
        return [
            {
                "id": e["id"],
                "name": e["name"],
                "source": e["source"],
                "sheets": e["summary"]["sheets"],
                "dashboards": e["summary"]["dashboards"],
                "calc_fields": e["summary"]["calc_fields"],
            }
            for e in self.data["entries"].values()
        ]

    def stats(self) -> dict:
        entries = list(self.data["entries"].values())
        return {
            "total_workbooks": len(entries),
            "from_cloud": sum(1 for e in entries if e["source"] == "cloud"),
            "from_local": sum(1 for e in entries if e["source"] == "local"),
            "total_sheets": sum(e["summary"]["sheets"] for e in entries),
            "total_dashboards": sum(e["summary"]["dashboards"] for e in entries),
            "total_calc_fields": sum(e["summary"]["calc_fields"] for e in entries),
            "last_rebuild": self.data.get("last_full_rebuild"),
        }
