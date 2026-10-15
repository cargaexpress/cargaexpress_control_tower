from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.carrier import Carrier
from app.models.order import Order
from app.models.shipping_label import ShippingLabel
from app.schemas.guia import GuiaCreate
from app.services.exceptions import (
    DuplicateTrackingNumberError,
    EntityNotFoundError,
    TenantForbiddenError,
)


async def create_guia_for_order(
    db: AsyncSession,
    order_id: int,
    payload: GuiaCreate,
    tenant_brand_id: int | None = None,
) -> ShippingLabel:
    """
    Asocia y crea una guía de despacho para un pedido existente (RN-07).

    Validaciones:
    1. Existencia del pedido (404 si no existe).
    2. Aislamiento multitenant (RN-10): Si se especifica tenant_brand_id, el pedido debe pertenecer a dicha marca.
    3. Existencia de la transportadora (404 si no existe).
    4. Unicidad del tracking_number: no puede estar asignado previamente a ninguna guía.
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

    guia = ShippingLabel(
        order_id=order_id,
        carrier_id=payload.carrier_id,
        tracking_number=payload.tracking_number.strip(),
        weight_kg=payload.weight_kg,
        dispatch_id=payload.dispatch_id,
        status=payload.status.upper() if payload.status else "CREADO",
    )

    db.add(guia)
    await db.commit()
    await db.refresh(guia)
    return guia


async def get_guias_by_order(
    db: AsyncSession,
    order_id: int,
    tenant_brand_id: int | None = None,
) -> list[ShippingLabel]:
    """
    Retorna la lista de guías asociadas a un pedido (RN-07).

    Validaciones:
    1. Existencia del pedido (404 si no existe).
    2. Aislamiento multitenant (RN-10): Si se especifica tenant_brand_id, el pedido debe pertenecer a dicha marca.
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
