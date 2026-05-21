"""
tableau_client.py — Wrapper sobre tableauserverclient (TSC) + Metadata API.

Centraliza autenticación con PAT y expone operaciones de alto nivel:
- Listar proyectos, datasources, workbooks
- Descargar/publicar workbooks (.twb/.twbx)
- Refresh de datasources + monitoreo de jobs
- Query a la Metadata API (GraphQL) para campos de una datasource
"""

import os
import re
import time
import shutil
import tempfile
from contextlib import contextmanager
from typing import Optional
import tableauserverclient as TSC


# UUID estándar (formato LUID de Tableau): 8-4-4-4-12 hexa
_LUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _validate_luid(luid: str, kind: str = "id") -> Optional[str]:
    """
    Valida que un identificador siga el formato LUID/UUID de Tableau.
    Devuelve None si es válido, o un mensaje de error si no.
    Usado como sanitización antes de interpolar en queries GraphQL o REST.
    """
    if not isinstance(luid, str) or not _LUID_RE.match(luid):
        return f"Invalid {kind}: expected UUID 8-4-4-4-12, got {luid!r}"
    return None


def _as_str(v):
    """
    Soporta tanto valores string directos (TSC nuevo) como objetos con .text
    (TSC viejo) cuando se procesan responses de la REST API.
    """
    if v is None:
        return None
    return v.text if hasattr(v, "text") else str(v)


class TableauClient:
    """Cliente unificado para operaciones contra Tableau Cloud."""

    def __init__(
        self,
        server_url: str = None,
        site_name: str = None,
        pat_name: str = None,
        pat_value: str = None,
    ):
        self.server_url = server_url or os.environ["TABLEAU_SERVER_URL"]
        self.site_name = (
            site_name if site_name is not None else os.environ.get("TABLEAU_SITE_NAME", "")
        )
        self.pat_name = pat_name or os.environ["TABLEAU_PAT_NAME"]
        self.pat_value = pat_value or os.environ["TABLEAU_PAT_VALUE"]
        # Cache id->name de proyectos. La REST API de Tableau Cloud no acepta
        # `projectId` como filter key en workbooks/datasources, solo `projectName`.
        # Cacheamos para no repegar list_projects en cada llamada.
        self._project_name_cache: dict[str, str] = {}

    def _resolve_project_name(self, project_id: str) -> Optional[str]:
        """Devuelve el nombre del proyecto dado su LUID. Cacheado."""
        if not project_id:
            return None
        if project_id in self._project_name_cache:
            return self._project_name_cache[project_id]
        for p in self.list_projects():
            self._project_name_cache[p["id"]] = p["name"]
        return self._project_name_cache.get(project_id)

    def _auth(self) -> TSC.PersonalAccessTokenAuth:
        return TSC.PersonalAccessTokenAuth(
            token_name=self.pat_name,
            personal_access_token=self.pat_value,
            site_id=self.site_name,
        )

    @contextmanager
    def session(self):
        """Context manager: yielda un server autenticado y firma out al salir."""
        server = TSC.Server(self.server_url, use_server_version=True)
        auth = self._auth()
        with server.auth.sign_in(auth):
            yield server

    # ─────────────────────────────────────────
    #  LISTING
    # ─────────────────────────────────────────

    def list_projects(self) -> list:
        with self.session() as s:
            projects = list(TSC.Pager(s.projects))
            return [
                {"id": p.id, "name": p.name, "description": p.description or ""}
                for p in projects
            ]

    def list_datasources(self, project_id: Optional[str] = None) -> list:
        # Resolvemos project_name ANTES de abrir la sesión, porque Tableau PAT
        # solo permite una sesión activa a la vez (sign-in anidado invalida la
        # sesión externa con 401).
        project_name = self._resolve_project_name(project_id) if project_id else None
        if project_id and not project_name:
            return []
        with self.session() as s:
            if project_id:
                req = TSC.RequestOptions()
                req.filter.add(
                    TSC.Filter(
                        TSC.RequestOptions.Field.ProjectName,
                        TSC.RequestOptions.Operator.Equals,
                        project_name,
                    )
                )
                items = list(TSC.Pager(s.datasources, req))
            else:
                items = list(TSC.Pager(s.datasources))
            return [
                {
                    "id": d.id,
                    "name": d.name,
                    "project_id": d.project_id,
                    "project_name": d.project_name,
                    "content_url": d.content_url,
                    "type": d.datasource_type,
                    "has_extracts": d.has_extracts,
                    "updated_at": str(d.updated_at) if d.updated_at else None,
                }
                for d in items
            ]

    def list_workbooks(self, project_id: Optional[str] = None) -> list:
        # Resolvemos project_name ANTES de abrir la sesión, porque Tableau PAT
        # solo permite una sesión activa a la vez (sign-in anidado invalida la
        # sesión externa con 401).
        project_name = self._resolve_project_name(project_id) if project_id else None
        if project_id and not project_name:
            return []
        with self.session() as s:
            if project_id:
                req = TSC.RequestOptions()
                req.filter.add(
                    TSC.Filter(
                        TSC.RequestOptions.Field.ProjectName,
                        TSC.RequestOptions.Operator.Equals,
                        project_name,
                    )
                )
                items = list(TSC.Pager(s.workbooks, req))
            else:
                items = list(TSC.Pager(s.workbooks))
            return [
                {
                    "id": w.id,
                    "name": w.name,
                    "project_id": w.project_id,
                    "project_name": w.project_name,
                    "content_url": w.content_url,
                    "webpage_url": w.webpage_url,
                    "updated_at": str(w.updated_at) if w.updated_at else None,
                }
                for w in items
            ]

    # ─────────────────────────────────────────
    #  DOWNLOAD / PUBLISH
    # ─────────────────────────────────────────

    def download_workbook(
        self,
        workbook_id: str,
        save_dir: Optional[str] = None,
        include_extract: bool = False,
    ) -> str:
        """
        Descarga un workbook. Retorna la path local al archivo.
        Por default no incluye el extract (más liviano para edición).
        """
        target_dir = save_dir or tempfile.mkdtemp(prefix="tableau_wb_")
        os.makedirs(target_dir, exist_ok=True)
        with self.session() as s:
            path = s.workbooks.download(
                workbook_id,
                filepath=target_dir,
                include_extract=include_extract,
            )
            return path

    def publish_workbook(
        self,
        twb_path: str,
        project_id: str,
        workbook_name: str,
        mode: str = "overwrite",
        show_tabs: bool = True,
    ) -> dict:
        publish_mode = {
            "overwrite": TSC.Server.PublishMode.Overwrite,
            "createnew": TSC.Server.PublishMode.CreateNew,
            "append": TSC.Server.PublishMode.Append,
        }[mode]
        with self.session() as s:
            item = TSC.WorkbookItem(
                project_id=project_id,
                name=workbook_name,
                show_tabs=show_tabs,
            )
            published = s.workbooks.publish(item, twb_path, publish_mode)
            return {
                "id": published.id,
                "name": published.name,
                "url": published.webpage_url,
                "project_id": published.project_id,
            }

    def download_datasource(
        self,
        datasource_id: str,
        save_dir: Optional[str] = None,
        include_extract: bool = False,
    ) -> str:
        """
        Descarga una datasource publicada como .tds (sin extract) o .tdsx (con extract).
        Retorna la path local al archivo.
        """
        target_dir = save_dir or tempfile.mkdtemp(prefix="tableau_ds_")
        os.makedirs(target_dir, exist_ok=True)
        with self.session() as s:
            path = s.datasources.download(
                datasource_id,
                filepath=target_dir,
                include_extract=include_extract,
            )
            return path

    def publish_datasource(
        self,
        tds_path: str,
        project_id: str,
        name: str,
        mode: str = "overwrite",
        db_username: Optional[str] = None,
        db_password: Optional[str] = None,
        embed_credentials: bool = True,
        auto_extract: bool = True,
        extract_wait_seconds: int = 240,
    ) -> dict:
        """
        Publica un .tds o .tdsx a Tableau Cloud.

        Args:
            tds_path: path local al .tds (live) o .tdsx (con extract).
            project_id: LUID del proyecto destino.
            name: nombre de la datasource publicada.
            mode: 'overwrite' (default), 'createnew', o 'append'.
            db_username: usuario de la BD para embeder en la conexión.
            db_password: password de la BD. Si se pasa, se embebe (necesario
                para que los refreshes automáticos funcionen sin re-prompt).
            embed_credentials: si True (default), las creds quedan guardadas
                cifradas en Tableau Cloud para refresh automatizado.
            auto_extract: si True (default), después de publicar dispara
                `create_extract` automáticamente. Convierte la DS de live a
                extract — los workbooks que la usen publican mucho más rápido.
                Pone has_extracts=True. Sin esto, el DS queda como live.
            extract_wait_seconds: cuánto esperar a que el extract se materialice
                antes de devolver. 0 = no esperar (job async sigue corriendo).
        """
        publish_mode = {
            "overwrite": TSC.Server.PublishMode.Overwrite,
            "createnew": TSC.Server.PublishMode.CreateNew,
            "append": TSC.Server.PublishMode.Append,
        }[mode]
        conn_creds = None
        if db_username and db_password:
            conn_creds = TSC.ConnectionCredentials(
                name=db_username,
                password=db_password,
                embed=embed_credentials,
            )
        with self.session() as s:
            item = TSC.DatasourceItem(project_id=project_id, name=name)
            kwargs = {}
            if conn_creds is not None:
                kwargs["connection_credentials"] = conn_creds
            published = s.datasources.publish(item, tds_path, publish_mode, **kwargs)
            result = {
                "id": published.id,
                "name": published.name,
                "url": published.webpage_url,
                "project_id": published.project_id,
                "content_url": published.content_url,
                "type": published.datasource_type,
                "has_extracts": published.has_extracts,
            }

            # Auto-conversión a extract: convierte la DS de live → extract.
            # Workbooks que la usen publican 10-30× más rápido porque la
            # validation no hace queries reales a la BD source.
            if auto_extract and not published.has_extracts:
                try:
                    refreshed = s.datasources.get_by_id(published.id)
                    job = s.datasources.create_extract(refreshed, encrypt=False)
                    result["create_extract_job_id"] = job.id
                    result["create_extract_mode"] = str(job.mode)

                    # Esperar a que has_extracts=True (la API no soporta
                    # pollear este job type, polleamos el DS directo)
                    if extract_wait_seconds > 0:
                        import time
                        start = time.time()
                        polled_extract = False
                        while time.time() - start < extract_wait_seconds:
                            check = s.datasources.get_by_id(published.id)
                            if check.has_extracts:
                                polled_extract = True
                                result["has_extracts"] = True
                                result["extract_wait_actual_seconds"] = round(time.time() - start, 1)
                                break
                            time.sleep(10)
                        if not polled_extract:
                            result["extract_warning"] = (
                                f"create_extract dispared (job {job.id}) "
                                f"pero has_extracts sigue False después de "
                                f"{extract_wait_seconds}s. Probablemente el job "
                                f"sigue corriendo async."
                            )
                except Exception as e:
                    result["extract_error"] = f"{type(e).__name__}: {e}"

            return result

    def create_extract_for_datasource(
        self,
        datasource_id: str,
        encrypt: bool = False,
        wait_seconds: int = 240,
    ) -> dict:
        """
        Crea un extract sobre una datasource publicada que está en modo live.

        Convierte la DS de live → extract. Después de esto, los workbooks que
        la consuman validan/publican mucho más rápido.

        Args:
            datasource_id: LUID de la datasource.
            encrypt: si True, el extract queda encriptado en el server.
            wait_seconds: tiempo máximo a esperar la materialización del
                extract. 0 = devuelve enseguida (job sigue async).

        Nota: la REST API no soporta pollear el job de create_extract por id
        (devuelve 400031). Polleamos el datasource directo hasta que
        has_extracts=True.
        """
        with self.session() as s:
            ds = s.datasources.get_by_id(datasource_id)
            if ds.has_extracts:
                return {
                    "datasource_id": datasource_id,
                    "name": ds.name,
                    "already_extract": True,
                    "has_extracts": True,
                }
            job = s.datasources.create_extract(ds, encrypt=encrypt)
            result = {
                "datasource_id": datasource_id,
                "name": ds.name,
                "job_id": job.id,
                "job_mode": str(job.mode),
                "has_extracts": False,
            }
            if wait_seconds > 0:
                import time
                start = time.time()
                while time.time() - start < wait_seconds:
                    check = s.datasources.get_by_id(datasource_id)
                    if check.has_extracts:
                        result["has_extracts"] = True
                        result["wait_actual_seconds"] = round(time.time() - start, 1)
                        break
                    time.sleep(10)
                if not result["has_extracts"]:
                    result["warning"] = (
                        f"create_extract triggered pero has_extracts sigue False "
                        f"después de {wait_seconds}s. El job sigue async."
                    )
            return result

    def backup_workbook(self, workbook_id: str) -> dict:
        """
        Crea una copia del workbook con sufijo '_backup_YYYY-MM-DD' en el mismo proyecto.
        Útil antes de operaciones destructivas.

        Seguridad: limpia el tempdir (que contiene el extract con datos reales)
        después de subir el backup, incluso si la publicación falla. Valida el
        workbook_id como UUID antes de cualquier operación de Cloud.
        """
        from datetime import date

        err = _validate_luid(workbook_id, "workbook_id")
        if err:
            return {"error": err}

        tmp = tempfile.mkdtemp(prefix="tableau_bkp_")
        try:
            with self.session() as s:
                wb = s.workbooks.get_by_id(workbook_id)
                path = s.workbooks.download(
                    workbook_id, filepath=tmp, include_extract=True
                )
                backup_name = f"{wb.name}_backup_{date.today().isoformat()}"
                item = TSC.WorkbookItem(
                    project_id=wb.project_id,
                    name=backup_name,
                    show_tabs=wb.show_tabs,
                )
                backup = s.workbooks.publish(
                    item, path, TSC.Server.PublishMode.CreateNew
                )
                return {
                    "backup_id": backup.id,
                    "backup_name": backup.name,
                    "backup_url": backup.webpage_url,
                }
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ─────────────────────────────────────────
    #  REFRESH + JOBS
    # ─────────────────────────────────────────

    def refresh_datasource(self, datasource_id: str) -> dict:
        with self.session() as s:
            job = s.datasources.refresh(datasource_id)
            return {"job_id": job.id, "status": job.status, "type": "refresh_extract"}

    def check_job(self, job_id: str) -> dict:
        with self.session() as s:
            job = s.jobs.get_by_id(job_id)
            return {
                "id": job.id,
                "status": job.finish_code if job.finish_code is not None else "running",
                "type": job.type,
                "created": str(job.created_at) if job.created_at else None,
                "started": str(job.started_at) if job.started_at else None,
                "ended": str(job.ended_at) if job.ended_at else None,
            }

    def refresh_and_wait(
        self,
        datasource_id: str,
        timeout_seconds: int = 600,
        poll_interval: int = 10,
    ) -> dict:
        """Dispara refresh y espera hasta que termine o se cumpla timeout."""
        info = self.refresh_datasource(datasource_id)
        job_id = info["job_id"]
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            status = self.check_job(job_id)
            if status["status"] != "running":
                return {
                    **status,
                    "elapsed_seconds": int(time.time() - (deadline - timeout_seconds)),
                }
            time.sleep(poll_interval)
        return {
            "id": job_id,
            "status": "timeout",
            "message": f"No finalizó en {timeout_seconds}s",
        }

    # ─────────────────────────────────────────
    #  METADATA API (GraphQL)
    # ─────────────────────────────────────────

    def get_datasource_fields(self, datasource_id: str) -> dict:
        """
        Obtiene campos de una datasource publicada vía Metadata API.
        Retorna nombre, tipo de dato, role (dimension/measure), visibilidad.

        Seguridad: valida que el datasource_id tenga formato UUID antes de
        interpolarlo en la query GraphQL.
        """
        invalid = _validate_luid(datasource_id, "datasource_id")
        if invalid:
            return {"error": invalid}

        query = (
            "{\n"
            '  publishedDatasourcesConnection(filter: {luid: "%s"}) {\n'
            "    nodes {\n"
            "      name\n"
            "      luid\n"
            "      hasExtracts\n"
            "      fieldsConnection {\n"
            "        nodes {\n"
            "          name\n"
            "          dataCategory\n"
            "          role\n"
            "          dataType\n"
            "          isHidden\n"
            "          ... on CalculatedField {\n"
            "            formula\n"
            "          }\n"
            "        }\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}\n"
        ) % datasource_id

        with self.session() as s:
            try:
                result = s.metadata.query(query)
                nodes = (
                    result.get("data", {})
                    .get("publishedDatasourcesConnection", {})
                    .get("nodes", [])
                )
                if not nodes:
                    return {"error": "Datasource no encontrada o sin permisos de Metadata API"}
                ds = nodes[0]
                fields = ds["fieldsConnection"]["nodes"]
                return {
                    "datasource_name": ds["name"],
                    "datasource_id": ds["luid"],
                    "has_extracts": ds.get("hasExtracts"),
                    "fields": [f for f in fields if not f.get("isHidden")],
                    "fields_hidden": [f for f in fields if f.get("isHidden")],
                    "field_count": len(fields),
                }
            except Exception as e:
                return {"error": f"Metadata API falló: {str(e)}"}

    def site_info(self) -> dict:
        with self.session() as s:
            info = s.server_info.get()
            return {
                "server_url": self.server_url,
                "site_name": self.site_name or "(default)",
                "product_version": _as_str(info.product_version),
                "rest_api_version": _as_str(info.rest_api_version),
                "site_id": s.site_id,
            }
