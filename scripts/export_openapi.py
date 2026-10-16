#!/usr/bin/env python3
"""Script to export FastAPI OpenAPI contract to docs/api/openapi.json.

Meets deliverable E-05 (FastAPI I & II):
- Loads the FastAPI application.
- Generates JSON schema with readable indentation (2 spaces).
- Saves the file to docs/api/openapi.json.
"""

import json
import os
import sys
from pathlib import Path

# Add backend to sys.path to allow importing app.main
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Minimal environment variables to initialize Settings() without error when no .env is loaded
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://cargaexpress:cargaexpress@localhost:5432/cargaexpress"
)

from app.main import app  # noqa: E402


def export_openapi_schema(output_path: Path | None = None) -> Path:
    """Export OpenAPI schema as formatted JSON."""
    if output_path is None:
        output_path = REPO_ROOT / "docs" / "api" / "openapi.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    openapi_data = app.openapi()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"✅ OpenAPI schema successfully exported to: {output_path}")
    return output_path


if __name__ == "__main__":
    export_openapi_schema()
