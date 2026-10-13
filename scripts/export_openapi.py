#!/usr/bin/env python3
"""Script para exportar el contrato OpenAPI de FastAPI a docs/api/openapi.json.

Cumple con el entregable E-05 (FastAPI I & II):
- Carga la aplicación FastAPI.
- Genera el schema JSON con indentación legible (2 espacios).
- Guarda el archivo en docs/api/openapi.json.
"""

import json
import os
import sys
from pathlib import Path

# Agregar backend al sys.path para poder importar app.main
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Variables mínimas para que Settings() inicialice sin error si no hay .env cargado
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://cargaexpress:cargaexpress@localhost:5432/cargaexpress")

from app.main import app  # noqa: E402


def export_openapi_schema(output_path: Path | None = None) -> Path:
    """Exporta el esquema OpenAPI como JSON formateado."""
    if output_path is None:
        output_path = REPO_ROOT / "docs" / "api" / "openapi.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    openapi_data = app.openapi()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"✅ Esquema OpenAPI exportado exitosamente a: {output_path}")
    return output_path


if __name__ == "__main__":
    export_openapi_schema()
