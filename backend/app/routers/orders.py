from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.order import (
    OrderCreate,
    OrderListResponse,
    OrderRead,
    OrderStatusUpdate,
)
from app.services import order_service
from app.services.exceptions import EntityNotFoundError

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
