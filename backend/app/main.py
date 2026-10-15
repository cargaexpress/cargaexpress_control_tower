from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.routers import admin_mapeo_estados, admin_state_mapping, health, orders
from app.schemas.errors import HTTPErrorResponse

openapi_tags = [
    {
        "name": "health",
        "description": "Verificación de disponibilidad de la API y conectividad con la base de datos.",
    },
    {
        "name": "pedidos",
        "description": "Gestión del ciclo de vida de pedidos WMS: creación, consulta por ID, listado paginado y actualización de estados.",
    },
    {
        "name": "admin: mapeo de estados",
        "description": "Administración de catálogos de traducción de estados de transportadoras hacia el vocabulario canónico (HU-15).",
    },
    {
        "name": "admin: state mapping",
        "description": "Operaciones CRUD y resolución de estados en caché en tiempo real (HU-12).",
    },
    {
        "name": "contrato openapi",
        "description": "Descarga e inspección interactiva del contrato OpenAPI / Swagger (Entregable E-05).",
    },
]

app = FastAPI(
    title="CargaExpress Supply Chain API",
    version="1.0.0",
    description=(
        "Torre de Control Logística CargaExpress: APIs para orquestación de pedidos WMS, "
        "tracking de transportadoras, mapeo dinámico de estados y gestión de anomalías."
    ),
    openapi_tags=openapi_tags,
    docs_url="/docs",
    redoc_url="/redoc",
    responses={
        400: {"model": HTTPErrorResponse, "description": "Solicitud errónea o datos inválidos."},
        401: {"model": HTTPErrorResponse, "description": "No autorizado (Falta o es incorrecto el token de autenticación)."},
        404: {"model": HTTPErrorResponse, "description": "Recurso no encontrado."},
        422: {"description": "Error de validación en la entidad o payload enviado."},
        500: {"model": HTTPErrorResponse, "description": "Error interno del servidor."},
    },
)

# Inclusión de routers modulares
app.include_router(health.router)
app.include_router(admin_state_mapping.router)
app.include_router(admin_mapeo_estados.router)
app.include_router(orders.router)


@app.get(
    "/docs/api/openapi.json",
    tags=["contrato openapi"],
    summary="Exportar especificación OpenAPI en formato JSON",
    description="Retorna el esquema OpenAPI 3.1 completo y serializado de la aplicación.",
    response_class=JSONResponse,
)
async def get_openapi_spec() -> JSONResponse:
    """Entrega el esquema OpenAPI completo en formato JSON para consumo estático o herramientas externas."""
    return JSONResponse(content=app.openapi())
