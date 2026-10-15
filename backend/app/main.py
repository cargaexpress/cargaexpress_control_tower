from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.routers import admin_carrier_state_mapping, admin_state_mapping, health, orders
from app.schemas.errors import HTTPErrorResponse

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
        "description": "Download and interactive inspection of OpenAPI / Swagger contract.",
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
    docs_url="/docs",
    redoc_url="/redoc",
    responses={
        400: {"model": HTTPErrorResponse, "description": "Bad request or invalid input."},
        401: {"model": HTTPErrorResponse, "description": "Unauthorized (missing or invalid credentials)."},
        404: {"model": HTTPErrorResponse, "description": "Resource not found."},
        422: {"description": "Validation error in entity or payload."},
        500: {"model": HTTPErrorResponse, "description": "Internal server error."},
    },
)

# Modular routers
app.include_router(health.router)
app.include_router(admin_state_mapping.router)
app.include_router(admin_carrier_state_mapping.router)
app.include_router(orders.router)


@app.get(
    "/docs/api/openapi.json",
    tags=["openapi contract"],
    summary="Export OpenAPI specification in JSON format",
    description="Returns full application OpenAPI 3.1 serialized schema.",
    response_class=JSONResponse,
)
async def get_openapi_spec() -> JSONResponse:
    """Deliver full OpenAPI schema in JSON format for static consumption or external tooling."""
    return JSONResponse(content=app.openapi())
