from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ShippingLabel
from app.schemas.errors import HTTPErrorResponse
from app.schemas.order import (
    OrderCreate,
    OrderListResponse,
    OrderRead,
    OrderStatusUpdate,
)
from app.schemas.shipping_label import ShippingLabelCreate, ShippingLabelResponse
from app.services import order_service, shipping_label_service
from app.services.exceptions import (
    DuplicateTrackingNumberError,
    EntityNotFoundError,
    TenantForbiddenError,
)

# The router translates HTTP requests/errors; persistence rules stay in the service.
router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.post(
    "",
    response_model=OrderRead,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create a new order with lines and recipient (HU-13)",
    description="Create an order with its mandatory child lines and recipient details. Validates that referenced brand, distribution center, and shipment type exist.",
    responses={
        201: {"description": "Order created successfully.", "model": OrderRead},
        400: {"description": "Bad request or invalid input.", "model": HTTPErrorResponse},
        404: {"description": "Referenced brand, distribution center, or shipment type not found.", "model": HTTPErrorResponse},
        422: {"description": "Validation error in entity or payload."},
    },
)
async def create_order(payload: OrderCreate, db: AsyncSession = Depends(get_db)) -> OrderRead:
    """Create a new order alongside line items and recipient details."""
    try:
        order = await order_service.create_order(db, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return order


@router.get(
    "",
    response_model=OrderListResponse,
    status_code=http_status.HTTP_200_OK,
    summary="List orders with pagination (HU-13)",
    description="Retrieve a paginated list of orders, including total count and pagination metadata.",
    responses={
        200: {"description": "List of orders retrieved successfully.", "model": OrderListResponse},
        422: {"description": "Validation error in pagination query parameters."},
    },
)
async def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> OrderListResponse:
    """Retrieve orders with pagination."""
    items, total = await order_service.list_orders(db, skip, limit)
    return OrderListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get(
    "/{order_id}",
    response_model=OrderRead,
    status_code=http_status.HTTP_200_OK,
    summary="Retrieve order by ID (HU-13)",
    description="Retrieve full details for a single order by its ID, including recipient and order lines.",
    responses={
        200: {"description": "Order retrieved successfully.", "model": OrderRead},
        404: {"description": "Order not found.", "model": HTTPErrorResponse},
        422: {"description": "Validation error in order ID path parameter."},
    },
)
async def get_order(order_id: int, db: AsyncSession = Depends(get_db)) -> OrderRead:
    """Retrieve an order by its identifier."""
    order = await order_service.get_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="order not found")
    return order


@router.patch(
    "/{order_id}/status",
    response_model=OrderRead,
    status_code=http_status.HTTP_200_OK,
    summary="Update order status (HU-13)",
    description="Update the canonical lifecycle status of an existing order.",
    responses={
        200: {"description": "Order status updated successfully.", "model": OrderRead},
        404: {"description": "Order not found.", "model": HTTPErrorResponse},
        422: {"description": "Validation error in order ID or status payload."},
    },
)
async def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    """Update order status."""
    order = await order_service.update_order_status(db, order_id, payload.status)
    if order is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="order not found")
    return order


@router.post(
    "/{order_id}/shipping-labels",
    response_model=ShippingLabelResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Associate shipping label with an order (RN-07)",
    responses={
        201: {"description": "Shipping label created and associated successfully", "model": ShippingLabelResponse},
        400: {"description": "Validation error or duplicate tracking number", "model": HTTPErrorResponse},
        403: {"description": "Access denied: order does not belong to brand (RN-10)", "model": HTTPErrorResponse},
        404: {"description": "Order or carrier not found", "model": HTTPErrorResponse},
        409: {"description": "Conflict: tracking number already exists", "model": HTTPErrorResponse},
    },
)
async def create_shipping_label(
    order_id: int,
    payload: ShippingLabelCreate,
    x_brand_id: int | None = Header(default=None, alias="X-Brand-Id"),
    db: AsyncSession = Depends(get_db),
) -> ShippingLabel:
    """Register and associate a new shipping label with the specified order."""
    try:
        shipping_label = await shipping_label_service.create_shipping_label_for_order(
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
    return shipping_label


@router.get(
    "/{order_id}/shipping-labels",
    response_model=list[ShippingLabelResponse],
    status_code=http_status.HTTP_200_OK,
    summary="List shipping labels for an order (RN-07)",
    responses={
        200: {"description": "List of shipping labels associated with order", "model": list[ShippingLabelResponse]},
        403: {"description": "Access denied: order does not belong to brand (RN-10)", "model": HTTPErrorResponse},
        404: {"description": "Order not found", "model": HTTPErrorResponse},
    },
)
async def get_shipping_labels(
    order_id: int,
    x_brand_id: int | None = Header(default=None, alias="X-Brand-Id"),
    db: AsyncSession = Depends(get_db),
) -> list[ShippingLabel]:
    """Retrieve all shipping labels associated with the specified order."""
    try:
        shipping_labels = await shipping_label_service.get_shipping_labels_by_order(
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
    return shipping_labels
