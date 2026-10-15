from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.carrier import Carrier
from app.models.order import Order
from app.models.shipping_label import ShippingLabel
from app.schemas.shipping_label import ShippingLabelCreate
from app.services.exceptions import (
    DuplicateTrackingNumberError,
    EntityNotFoundError,
    TenantForbiddenError,
)


async def create_shipping_label_for_order(
    db: AsyncSession,
    order_id: int,
    payload: ShippingLabelCreate,
    tenant_brand_id: int | None = None,
) -> ShippingLabel:
    """Associate and create a shipping label for an existing order (RN-07).

    Validations:
    1. Order existence (404 if missing).
    2. Multitenant isolation (RN-10): If tenant_brand_id is provided, order must belong to that brand.
    3. Carrier existence (404 if missing).
    4. Uniqueness of tracking_number: cannot be already assigned to any shipping label.
    """
    order = await db.get(Order, order_id)
    if order is None:
        raise EntityNotFoundError("order", order_id)

    if tenant_brand_id is not None and order.brand_id != tenant_brand_id:
        raise TenantForbiddenError(
            f"El pedido {order_id} no pertenece a la marca {tenant_brand_id}"
        )

    carrier = await db.get(Carrier, payload.carrier_id)
    if carrier is None:
        raise EntityNotFoundError("carrier", payload.carrier_id)

    existing_stmt = select(ShippingLabel).where(
        ShippingLabel.tracking_number == payload.tracking_number.strip()
    )
    existing_label = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing_label is not None:
        raise DuplicateTrackingNumberError(payload.tracking_number.strip())

    shipping_label = ShippingLabel(
        order_id=order_id,
        carrier_id=payload.carrier_id,
        tracking_number=payload.tracking_number.strip(),
        weight_kg=payload.weight_kg,
        dispatch_id=payload.dispatch_id,
        status=payload.status.upper() if payload.status else "CREADO",
    )

    db.add(shipping_label)
    await db.commit()
    await db.refresh(shipping_label)
    return shipping_label


async def get_shipping_labels_by_order(
    db: AsyncSession,
    order_id: int,
    tenant_brand_id: int | None = None,
) -> list[ShippingLabel]:
    """Return the list of shipping labels associated with an order (RN-07).

    Validations:
    1. Order existence (404 if missing).
    2. Multitenant isolation (RN-10): If tenant_brand_id is provided, order must belong to that brand.
    """
    order = await db.get(Order, order_id)
    if order is None:
        raise EntityNotFoundError("order", order_id)

    if tenant_brand_id is not None and order.brand_id != tenant_brand_id:
        raise TenantForbiddenError(
            f"El pedido {order_id} no pertenece a la marca {tenant_brand_id}"
        )

    stmt = (
        select(ShippingLabel)
        .where(ShippingLabel.order_id == order_id)
        .order_by(ShippingLabel.label_id)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# Backwards compatibility aliases
create_guia_for_order = create_shipping_label_for_order
get_guias_by_order = get_shipping_labels_by_order
