# syntax=docker/dockerfile:1
#
# Dockerfile del backend de CargaExpress (FastAPI + Python 3.12 + uv).
# Toda la configuración (base de datos, entorno, credenciales) llega por
# VARIABLES DE ENTORNO al iniciar el contenedor. Nada sensible va aquí.

# ---------- Etapa 1: instalar dependencias ----------
FROM python:3.12-slim AS builder

# uv fijado a una versión que entiende el formato de uv.lock del proyecto
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Solo los archivos de dependencias: Docker reutiliza la caché si el código cambia.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------- Etapa 2: imagen final ligera ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Usuario sin privilegios
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser alembic.ini ./

USER appuser

# Variables que la app lee (ver app/config.py). No se definen aquí a propósito:
# se inyectan al ejecutar el contenedor (docker compose / docker run -e / --env-file).
#   APP_ENV       entorno (development, production...)
#   DATABASE_URL  postgresql+asyncpg://usuario:clave@host:5432/base
#   SQL_ECHO      true/false

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
