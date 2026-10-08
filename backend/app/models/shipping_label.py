from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ShippingLabel(Base):
    __tablename__ = "shipping_labels"

    label_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.order_id"), nullable=False)
    carrier_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("carriers.carrier_id"), nullable=False)
    tracking_number: Mapped[str] = mapped_column(String, nullable=False)
    dispatch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dispatches.dispatch_id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped["Order"] = relationship(back_populates="shipping_labels")
    carrier: Mapped["Carrier"] = relationship(back_populates="shipping_labels")
    dispatch: Mapped["Dispatch | None"] = relationship(back_populates="shipping_labels")
    label_items: Mapped[list["ShippingLabelItem"]] = relationship(back_populates="shipping_label")
