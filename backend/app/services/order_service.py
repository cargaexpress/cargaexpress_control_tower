from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.brand import Brand
from app.models.distribution_center import DistributionCenter
from app.models.order import Order
from app.models.order_line import OrderLine
from app.models.order_recipient import OrderRecipient
from app.models.shipment_type import ShipmentType
from app.schemas.order import OrderCreate
from app.services.exceptions import DuplicateOrderReferenceError, EntityNotFoundError

# Eager-load child records to return complete orders without per-row queries.
# Service functions isolate persistence from HTTP handling for reuse and testing.
_ORDER_LOAD_OPTIONS = (selectinload(Order.order_lines), selectinload(Order.recipient))


async def _get_or_404(db: AsyncSession, model, pk_value, entity_name: str):
    obj = await db.get(model, pk_value)
    if obj is None:
        raise EntityNotFoundError(entity_name, pk_value)
    return obj


async def create_order(db: AsyncSession, payload: OrderCreate, tenant_brand_id: int) -> Order:
    """Create an order with its lines and recipient (mandatory 1:1 relation).

    Uses the authenticated tenant brand and validates the remaining references;
    raises EntityNotFoundError if any reference is missing (translated to 404 by router).
    """
    await _get_or_404(db, Brand, tenant_brand_id, "brand")
    await _get_or_404(db, DistributionCenter, payload.dc_id, "distribution_center")
    await _get_or_404(db, ShipmentType, payload.shipment_type_code, "shipment_type")

    order = Order(
        brand_id=tenant_brand_id,
        dc_id=payload.dc_id,
        shipment_type_code=payload.shipment_type_code,
        brand_order_ref=payload.brand_order_ref,
        destination_country=payload.destination_country,
        destination_region=payload.destination_region,
        freight_value=payload.freight_value,
        status=payload.status,
    )

    for index, line in enumerate(payload.order_lines, start=1):
        order.order_lines.append(
            OrderLine(
                line_number=index,
                sku=line.sku,
                description=line.description,
                quantity_ordered=line.quantity_ordered,
            )
        )

    order.recipient = OrderRecipient(
        full_name=payload.recipient.full_name,
        email=payload.recipient.email,
        phone=payload.recipient.phone,
        address_line=payload.recipient.address_line,
        city=payload.recipient.city,
    )

    db.add(order)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateOrderReferenceError(payload.brand_order_ref) from exc
    await db.refresh(order, attribute_names=["order_lines", "recipient"])
    return order


async def get_order(db: AsyncSession, order_id: int, tenant_brand_id: int) -> Order | None:
    stmt = (
        select(Order)
        .where(Order.order_id == order_id, Order.brand_id == tenant_brand_id)
        .options(*_ORDER_LOAD_OPTIONS)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_orders(
    db: AsyncSession, tenant_brand_id: int, skip: int, limit: int
) -> tuple[list[Order], int]:
    # Stable ordering makes offset/limit pagination deterministic.
    items_stmt = (
        select(Order)
        .where(Order.brand_id == tenant_brand_id)
        .options(*_ORDER_LOAD_OPTIONS)
        .order_by(Order.order_id)
        .offset(skip)
        .limit(limit)
    )
    total_stmt = select(func.count()).select_from(Order).where(Order.brand_id == tenant_brand_id)

    items_result = await db.execute(items_stmt)
    total_result = await db.execute(total_stmt)

    items = list(items_result.scalars().all())
    total = total_result.scalar_one()
    return items, total


async def update_order_status(
    db: AsyncSession, order_id: int, new_status: str, tenant_brand_id: int
) -> Order | None:
    order = await get_order(db, order_id, tenant_brand_id)
    if order is None:
        return None
    order.status = new_status
    await db.commit()
    await db.refresh(order, attribute_names=["order_lines", "recipient"])
    return order
