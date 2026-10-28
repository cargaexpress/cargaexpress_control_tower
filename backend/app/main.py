import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.routers import (
    admin_carrier_state_mapping,
    admin_state_mapping,
    health,
    orders,
    type_b_sync,
    type_c_ingestion,
    webhooks,
)
from app.schemas.errors import HTTPErrorResponse

logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger("cargaexpress")

openapi_tags = [
    {
        "name": "health",
        "description": "API health check and database connectivity probe.",
    },
    {
        "name": "orders",
        "description": "WMS order lifecycle management: creation, query by ID, paginated listing, SLA calculation, and at-risk monitoring.",
    },
    {
        "name": "webhooks",
        "description": "Carrier webhook receiver for push tracking events (F3 / RNF-01).",
    },
    {
        "name": "connectors: type b",
        "description": "Polling connectors and synchronization hooks for Type B carriers (F4).",
    },
    {
        "name": "connectors: type c",
        "description": "Batch file ingestion connectors for Type C carriers (CSV/Excel) (F5).",
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


async def http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise TypeError("Starlette HTTP exception handler received an unexpected exception.")
    payload = HTTPErrorResponse(detail=str(exc.detail), error_code="HTTP_ERROR")
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


async def request_validation_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise TypeError("Request validation handler received an unexpected exception.")
    payload = HTTPErrorResponse(
        detail=[dict(error) for error in exc.errors()],
        error_code="VALIDATION_ERROR",
    )
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(payload.model_dump()),
    )


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application exception", exc_info=exc)
    payload = HTTPErrorResponse(detail="Internal server error.", error_code="INTERNAL_SERVER_ERROR")
    return JSONResponse(status_code=500, content=payload.model_dump())


def create_app() -> FastAPI:
    application = FastAPI(
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

    if settings.app_env != "production":

        @application.get("/docs/api/openapi.json")
        async def docs_api_openapi_json() -> JSONResponse:
            return JSONResponse(application.openapi())

    application.include_router(health.router)
    application.include_router(webhooks.router)
    application.include_router(type_b_sync.router)
    application.include_router(type_c_ingestion.router)
    application.include_router(admin_state_mapping.router)
    application.include_router(admin_carrier_state_mapping.router)
    application.include_router(orders.router)
    application.include_router(orders.alias_router)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    return application


app = create_app()
