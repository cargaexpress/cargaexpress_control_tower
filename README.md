# CargaExpress Supply Chain — Backend

API del backend de CargaExpress para la torre de control del negocio.

## Estado actual

- ✅ Endpoint de salud: `GET /api/v1/health`
- ⏳ El resto de módulos se agregan progresivamente

## Stack

- Python 3.12
- FastAPI
- SQLAlchemy 2.x + asyncpg
- Alembic
- Pydantic Settings
- uv
- pytest

## Requisitos previos

- Python 3.12 instalado
- [uv](https://docs.astral.sh/uv/) instalado
- PostgreSQL corriendo localmente o remotamente

## 1) Clonar y preparar el proyecto

```bash
git clone <repo-url>
cd cargaexpress_control_tower/backend
uv sync
```

Esto crea el entorno virtual `.venv` e instala las dependencias definidas en `pyproject.toml`.

## 2) Configurar variables de entorno

Desde la carpeta `backend`:

```bash
cp .env.example .env
```

Ajusta el archivo `.env` según tu entorno. La configuración base es:

```env
APP_ENV=development
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/cargaexpress
SQL_ECHO=false
```

## 3) Ejecutar el backend localmente

```bash
uv run uvicorn app.main:app --reload
```

La API queda disponible en:

- http://localhost:8000
- Swagger: http://localhost:8000/docs

## 4) Verificar que funciona

```bash
curl http://localhost:8000/api/v1/health
```

Respuesta esperada:

```json
{"status": "ok", "database": "up"}
```

Si `database` devuelve `"down"`, el servicio sigue vivo pero no pudo conectarse a PostgreSQL. Revisa la variable `DATABASE_URL` y que la base de datos esté disponible.

## 5) Ejecutar pruebas

```bash
uv run pytest -v
```

## 6) Migraciones con Alembic

Cuando agregues el primer modelo, puedes crear y aplicar migraciones con:

```bash
uv run alembic revision --autogenerate -m "crear tabla pedidos"
uv run alembic upgrade head
```

## Estructura del proyecto

```text
backend/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── routers/
│   ├── services/
│   ├── models/
│   └── schemas/
├── alembic/
├── tests/
├── .env.example
├── alembic.ini
├── pyproject.toml
└── .gitignore
```

## Notas

- Este repositorio no requiere pasos extra para funcionar en un entorno local estándar.
- El endpoint de salud es la primera verificación para confirmar que el backend está levantado y que la conexión a la base de datos responde.
