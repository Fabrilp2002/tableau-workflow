"""
verify.py — Smoke test del setup del Tableau Workflow Assistant.

Corre estos chequeos:
  1. Python 3.10+
  2. Dependencias instaladas (mcp, tableauserverclient, dotenv)
  3. .env presente y completo
  4. Conectividad a Tableau Cloud (site_info)
  5. Listado básico (list_projects, list_workbooks, list_datasources)
  6. Carpeta local TABLEAU_LOCAL_FOLDER existe (si está configurada)

Uso (desde el venv activado):
    python verify.py

Devuelve exit code 0 si todo OK, 1 si hay algún check rojo.
"""

import os
import sys
from pathlib import Path

OK = "[OK]  "
FAIL = "[FAIL]"
INFO = "[INFO]"

errors = []


def check_python_version():
    if sys.version_info < (3, 10):
        errors.append(f"Python {sys.version.split()[0]} < 3.10")
        print(f"{FAIL} Python {sys.version.split()[0]} (necesita >= 3.10)")
        return False
    print(f"{OK} Python {sys.version.split()[0]}")
    return True


def check_imports():
    missing = []
    for mod in ("mcp", "tableauserverclient", "dotenv"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        errors.append(f"Faltan paquetes: {', '.join(missing)}")
        print(f"{FAIL} Faltan paquetes: {', '.join(missing)}  →  corre install.bat")
        return False
    print(f"{OK} Dependencias OK (mcp, tableauserverclient, dotenv)")
    return True


def check_env():
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        errors.append(".env no existe")
        print(f"{FAIL} .env no encontrado en {env_path}")
        return False

    from dotenv import load_dotenv
    load_dotenv(env_path)

    required = ["TABLEAU_SERVER_URL", "TABLEAU_PAT_NAME", "TABLEAU_PAT_VALUE"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        errors.append(f".env incompleto: {', '.join(missing)}")
        print(f"{FAIL} .env incompleto: faltan {', '.join(missing)}")
        return False

    if os.environ.get("TABLEAU_PAT_VALUE") == "tu-secret-aqui":
        errors.append("TABLEAU_PAT_VALUE sigue con el placeholder")
        print(f"{FAIL} TABLEAU_PAT_VALUE sigue siendo 'tu-secret-aqui' — pegá tu PAT real")
        return False

    print(f"{OK} .env presente y con valores")
    print(f"      server: {os.environ['TABLEAU_SERVER_URL']}")
    print(f"      site:   {os.environ.get('TABLEAU_SITE_NAME', '(default)')}")
    print(f"      PAT:    {os.environ['TABLEAU_PAT_NAME']}")
    return True


def check_local_folder():
    folder = os.environ.get("TABLEAU_LOCAL_FOLDER", "").strip()
    if not folder:
        print(f"{INFO} TABLEAU_LOCAL_FOLDER vacío — saltando chequeo local")
        return True
    p = Path(folder)
    if not p.exists():
        errors.append(f"TABLEAU_LOCAL_FOLDER no existe: {folder}")
        print(f"{FAIL} TABLEAU_LOCAL_FOLDER no existe: {folder}")
        return False
    twbs = list(p.glob("**/*.twb*"))
    print(f"{OK} TABLEAU_LOCAL_FOLDER existe ({len(twbs)} archivos .twb/.twbx)")
    return True


def check_connectivity():
    try:
        from tableau_client import TableauClient
        info = TableauClient().site_info()
        print(f"{OK} Conectividad a Tableau Cloud")
        print(f"      product_version: {info.get('product_version')}")
        print(f"      rest_api:        {info.get('rest_api_version')}")
        print(f"      site_id:         {info.get('site_id')}")
        return True
    except Exception as e:
        errors.append(f"Conectividad falló: {e}")
        print(f"{FAIL} Conectividad falló: {e}")
        print(f"      Tips: PAT expirado? Server URL correcto? Site name (vacío para default)?")
        return False


def check_listing():
    try:
        from tableau_client import TableauClient
        client = TableauClient()
        projects = client.list_projects()
        workbooks = client.list_workbooks()
        datasources = client.list_datasources()
        print(f"{OK} Listing OK")
        print(f"      projects:    {len(projects)}")
        print(f"      workbooks:   {len(workbooks)}")
        print(f"      datasources: {len(datasources)}")
        return True
    except Exception as e:
        errors.append(f"Listing falló: {e}")
        print(f"{FAIL} Listing falló: {e}")
        return False


def main():
    print("=" * 60)
    print(" Tableau Workflow Assistant — Verify Setup")
    print("=" * 60)

    if not check_python_version():
        return 1
    if not check_imports():
        return 1
    if not check_env():
        return 1

    # Solo seguimos si tenemos venv + deps + .env
    check_local_folder()

    print()
    print(INFO, "Probando conectividad a Tableau Cloud …")
    if not check_connectivity():
        return 1
    check_listing()

    print()
    if errors:
        print(f"{FAIL} Hubo {len(errors)} problemas:")
        for e in errors:
            print(f"       - {e}")
        return 1

    print("=" * 60)
    print(" Todo OK — el MCP está listo para conectarse a Claude Desktop.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
