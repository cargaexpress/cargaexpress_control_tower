import logging
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.routers import (
    admin_carrier_state_mapping,
    admin_state_mapping,
    alerts,
    analytics,
    carriers,
    financial,
    health,
    orders,
    sla,
    type_a_sync,
    type_b_sync,
    type_c_ingestion,
    webhooks,
)
from app.schemas.errors import HTTPErrorResponse

logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger("cargaexpress")

openapi_tags = [
    # Group A: Operational API
    {"name": "Operational: Orders"},
    {"name": "Operational: Carriers"},
    {"name": "Operational: SLA & Compliance"},
    {"name": "Operational: Alerts"},
    {"name": "Operational: Financial"},
    {"name": "Operational: Analytics"},
    # Group B: Integration API
    {"name": "Integration: Webhooks"},
    {"name": "Integration: Connectors"},
    # Group C: Internal Process API
    {"name": "Internal Processes: Alerts"},
    {"name": "Internal Processes: Financial Settlements"},
    {"name": "Internal Processes: Analytics ETL"},
    # Group D: Administration API
    {"name": "Administration: State Mappings"},
    # Group E: Monitoring API
    {"name": "Monitoring: Health & Readiness"},
    # Legacy Compatibility Tags
    {"name": "health"},
    {"name": "orders"},
    {"name": "sla & compliance"},
    {"name": "alerts & risk monitoring"},
    {"name": "financial & penalties"},
    {"name": "analytics & data warehouse"},
    {"name": "webhooks"},
    {"name": "connectors: type a"},
    {"name": "connectors: type b"},
    {"name": "connectors: type c"},
    {"name": "admin: carrier state mapping"},
    {"name": "admin: state mapping"},
    {"name": "carriers"},
    {"name": "openapi contract"},
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
        openapi_tags=openapi_tags,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
    )

    if settings.app_env != "production":

        @application.get(
            "/docs/api/openapi.json", tags=["openapi contract"], summary="OpenAPI Schema"
        )
        async def docs_api_openapi_json() -> JSONResponse:
            return JSONResponse(application.openapi())

    def custom_openapi() -> dict[str, Any]:
        if application.openapi_schema:
            return application.openapi_schema
        openapi_schema = get_openapi(
            title=application.title,
            version=application.version,
            openapi_version=application.openapi_version,
            description=None,
            routes=application.routes,
            tags=application.openapi_tags,
            servers=application.servers,
            terms_of_service=application.terms_of_service,
            contact=application.contact,
            license_info=application.license_info,
        )
        for _path, path_item in openapi_schema.get("paths", {}).items():
            for method, op in path_item.items():
                if method.lower() in {"get", "post", "put", "patch", "delete"}:
                    op.pop("description", None)
                    if "summary" in op and op["summary"]:
                        op["summary"] = re.sub(
                            r"\s*\((?:HU-\d+|RN-\d+|FR-\d+|BR-\d+|F\d+|Internal process)[^)]*\)",
                            "",
                            op["summary"],
                        ).strip()
                    if "tags" in op and op["tags"]:
                        primary_tags = [t for t in op["tags"] if ":" in t]
                        if primary_tags:
                            op["tags"] = [primary_tags[0]]
        application.openapi_schema = openapi_schema
        return application.openapi_schema

    application.openapi = custom_openapi  # type: ignore[method-assign]

    application.include_router(health.router)
    application.include_router(webhooks.router)
    application.include_router(type_a_sync.router)
    application.include_router(type_b_sync.router)
    application.include_router(type_c_ingestion.router)
    application.include_router(admin_state_mapping.router)
    application.include_router(admin_carrier_state_mapping.router)
    application.include_router(orders.router)
    application.include_router(carriers.router)
    application.include_router(sla.router)
    application.include_router(alerts.router)
    application.include_router(financial.router)
    application.include_router(analytics.router)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    return application


app = create_app()
