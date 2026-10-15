from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ShippingLabel
from app.schemas.guia import GuiaCreate, GuiaResponse, HTTPErrorResponse
from app.schemas.order import (
    OrderCreate,
    OrderListResponse,
    OrderRead,
    OrderStatusUpdate,
)
from app.services import guia_service, order_service
from app.services.exceptions import (
    DuplicateTrackingNumberError,
    EntityNotFoundError,
    TenantForbiddenError,
)

# The router translates HTTP requests/errors; persistence rules stay in the service.
# Routes use Spanish resource naming to match the project's API convention.
# El router traduce solicitudes/errores HTTP; la lógica de datos vive en el servicio.
# Las rutas usan nombres en español según la convención de la API.
router = APIRouter(prefix="/api/v1/pedidos", tags=["pedidos"])


@router.post("", response_model=OrderRead, status_code=http_status.HTTP_201_CREATED)
async def create_order(payload: OrderCreate, db: AsyncSession = Depends(get_db)) -> OrderRead:
    try:
        order = await order_service.create_order(db, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return order


@router.get("", response_model=OrderListResponse)
async def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> OrderListResponse:
    items, total = await order_service.list_orders(db, skip, limit)
    return OrderListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(order_id: int, db: AsyncSession = Depends(get_db)) -> OrderRead:
    order = await order_service.get_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="order not found")
    return order


@router.patch("/{order_id}/status", response_model=OrderRead)
async def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    order = await order_service.update_order_status(db, order_id, payload.status)
    if order is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="order not found")
    return order


@router.post(
    "/{order_id}/guias",
    response_model=GuiaResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Asociar guía de despacho a un pedido (RN-07)",
    responses={
        201: {"description": "Guía creada y asociada exitosamente al pedido", "model": GuiaResponse},
        400: {"description": "Error de validación o tracking duplicado", "model": HTTPErrorResponse},
        403: {"description": "Acceso denegado: el pedido no pertenece a la marca (RN-10)", "model": HTTPErrorResponse},
        404: {"description": "Pedido o transportadora no encontrado", "model": HTTPErrorResponse},
        409: {"description": "Conflicto por guía de tracking ya existente", "model": HTTPErrorResponse},
    },
)
async def create_guia(
    order_id: int,
    payload: GuiaCreate,
    x_brand_id: int | None = Header(default=None, alias="X-Brand-Id"),
    db: AsyncSession = Depends(get_db),
) -> ShippingLabel:
    """Registra y asocia una nueva guía de despacho al pedido indicado."""
    try:
        guia = await guia_service.create_guia_for_order(
            db=db,
            order_id=order_id,
            payload=payload,
            tenant_brand_id=x_brand_id,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except TenantForbiddenError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except DuplicateTrackingNumberError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return guia


@router.get(
    "/{order_id}/guias",
    response_model=list[GuiaResponse],
    status_code=http_status.HTTP_200_OK,
    summary="Listar guías de despacho de un pedido (RN-07)",
    responses={
        200: {"description": "Lista de guías asociadas al pedido", "model": list[GuiaResponse]},
        403: {"description": "Acceso denegado: el pedido no pertenece a la marca (RN-10)", "model": HTTPErrorResponse},
        404: {"description": "Pedido no encontrado", "model": HTTPErrorResponse},
    },
)
async def get_guias(
    order_id: int,
    x_brand_id: int | None = Header(default=None, alias="X-Brand-Id"),
    db: AsyncSession = Depends(get_db),
) -> list[ShippingLabel]:
    """Obtiene el listado de todas las guías de despacho asociadas al pedido indicado."""
    try:
        guias = await guia_service.get_guias_by_order(
            db=db,
            order_id=order_id,
            tenant_brand_id=x_brand_id,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except TenantForbiddenError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    return guias
