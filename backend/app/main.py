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
    # =========================================================================
    # Group A: Operational API (Daily Control Tower operations)
    # =========================================================================
    {
        "name": "Operational: Orders",
        "description": "Daily operations: order creation, detail query, status updates, and shipping labels.",
    },
    {
        "name": "Operational: Carriers",
        "description": "Daily operations: carrier catalog query, detail view, and authenticated carrier profile.",
    },
    {
        "name": "Operational: SLA & Compliance",
        "description": "Daily operations: SLA tracking, delivery deadlines, at-risk shipments, brand and carrier metrics.",
    },
    {
        "name": "Operational: Alerts",
        "description": "Daily operations: operational alerts query for at-risk shipments/exceptions, and alert resolution.",
    },
    {
        "name": "Operational: Financial",
        "description": "Daily operations: responsibility attributions, freight penalties, settlements, and penalty configurations.",
    },
    {
        "name": "Operational: Analytics",
        "description": "Daily operations: high-level KPI metrics, SLA facts, and financial penalty facts consultation.",
    },
    # =========================================================================
    # Group B: Integration API (External carriers and simulators)
    # =========================================================================
    {
        "name": "Integration: Webhooks",
        "description": "External integration: push webhook tracking receiver with token and HMAC verification (Type A).",
    },
    {
        "name": "Integration: Connectors",
        "description": "External integration: polling connectors and batch file uploads for external carriers and simulators (Type A, B, C).",
    },
    # =========================================================================
    # Group C: Internal Process API (Controlled operations for internal services)
    # =========================================================================
    {
        "name": "Internal Processes: Alerts",
        "description": "Controlled internal operations: on-demand automated risk scanning and preventive alert generation.",
    },
    {
        "name": "Internal Processes: Financial Settlements",
        "description": "Controlled internal operations: biweekly financial netting settlement calculation and period generation.",
    },
    {
        "name": "Internal Processes: Analytics ETL",
        "description": "Controlled internal operations: dimensional star-schema analytical ETL pipeline execution.",
    },
    # =========================================================================
    # Group D: Administration API (State mapping configuration)
    # =========================================================================
    {
        "name": "Administration: State Mappings",
        "description": "Administrative operations: carrier raw status translation and canonical status mapping management.",
    },
    # =========================================================================
    # Group E: Monitoring API (Health and readiness probes)
    # =========================================================================
    {
        "name": "Monitoring: Health & Readiness",
        "description": "System monitoring: service availability health check and database connectivity readiness probe.",
    },
    # =========================================================================
    # Legacy Compatibility Tags
    # =========================================================================
    {"name": "health", "description": "Legacy alias: System health check."},
    {"name": "orders", "description": "Legacy alias: Orders operations."},
    {"name": "sla & compliance", "description": "Legacy alias: SLA and compliance."},
    {
        "name": "alerts & risk monitoring",
        "description": "Legacy alias: Alerts and risk monitoring.",
    },
    {"name": "financial & penalties", "description": "Legacy alias: Financial and penalties."},
    {
        "name": "analytics & data warehouse",
        "description": "Legacy alias: Analytics and data warehouse.",
    },
    {"name": "webhooks", "description": "Legacy alias: Webhooks."},
    {"name": "connectors: type a", "description": "Legacy alias: Connectors Type A."},
    {"name": "connectors: type b", "description": "Legacy alias: Connectors Type B."},
    {"name": "connectors: type c", "description": "Legacy alias: Connectors Type C."},
    {
        "name": "admin: carrier state mapping",
        "description": "Legacy alias: Carrier state mapping admin.",
    },
    {"name": "admin: state mapping", "description": "Legacy alias: State mapping admin."},
    {"name": "carriers", "description": "Legacy alias: Carriers catalog."},
    {"name": "openapi contract", "description": "OpenAPI metadata and contract validation."},
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
