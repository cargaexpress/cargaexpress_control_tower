import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import admin_carrier_state_mapping, admin_state_mapping, health, orders
from app.schemas.errors import HTTPErrorResponse

logging.basicConfig(level=getattr(logging, settings.app_env.upper(), logging.INFO))
logger = logging.getLogger("cargaexpress")

openapi_tags = [
    {
        "name": "health",
        "description": "API health check and database connectivity probe.",
    },
    {
        "name": "orders",
        "description": "WMS order lifecycle management: creation, query by ID, paginated listing, and shipping labels.",
    },
    {
        "name": "admin: carrier state mapping",
        "description": "Carrier status mapping administration for canonical status normalization (HU-15).",
    },
    {
        "name": "admin: state mapping",
        "description": "CRUD operations and real-time cached status translation (HU-12).",
    },
    {
        "name": "openapi contract",
        "description": "OpenAPI metadata and contract validation for the platform API surface.",
    },
]

app = FastAPI(
    title="CargaExpress Supply Chain API",
    version="1.0.0",
    description=(
        "CargaExpress Control Tower Logistics: APIs for WMS order orchestration, "
        "carrier tracking, dynamic state mapping, and exception management."
    ),
    openapi_tags=openapi_tags,
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
    openapi_url="/openapi.json" if settings.app_env != "production" else None,
)


@app.get("/docs/api/openapi.json")
async def docs_api_openapi_json() -> JSONResponse:
    return JSONResponse(app.openapi())

# Modular routers
app.include_router(health.router)
app.include_router(admin_state_mapping.router)
app.include_router(admin_carrier_state_mapping.router)
app.include_router(orders.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    payload = HTTPErrorResponse(detail=str(exc.detail), error_code="HTTP_ERROR")
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application exception", exc_info=exc)
    payload = HTTPErrorResponse(detail="Internal server error.", error_code="INTERNAL_SERVER_ERROR")
    return JSONResponse(status_code=500, content=payload.model_dump())
