from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.carrier import Carrier
    from app.models.shipping_label import ShippingLabel


class ShipmentAlert(Base):
    """Operational risk and SLA alerts for shipments (RN-04).

    Alert Types:
    - PREVENTIVE_24H: <= 24 business hours to deadline and not OUT_FOR_DELIVERY.
    - PROLONGED_EXCEPTION: EXCEPTION state unresolved for > 12 hours.
    """

    __tablename__ = "shipment_alerts"
    __table_args__ = (
        Index("ix_shipment_alerts_alert_type", "alert_type"),
        Index("ix_shipment_alerts_is_resolved", "is_resolved"),
        Index("ix_shipment_alerts_tracking_number", "tracking_number"),
        Index("ix_shipment_alerts_carrier_id", "carrier_id"),
        Index("ix_shipment_alerts_created_at", "created_at"),
    )

    alert_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    label_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shipping_labels.label_id", ondelete="CASCADE"), nullable=False
    )
    carrier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("carriers.carrier_id"), nullable=False
    )
    tracking_number: Mapped[str] = mapped_column(String, nullable=False)
    alert_type: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, default="WARNING", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    hours_remaining: Mapped[float | None] = mapped_column(Float, nullable=True)
    exception_duration_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    exception_detail: Mapped[str | None] = mapped_column(String, nullable=True)

    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    carrier: Mapped["Carrier"] = relationship()
    shipping_label: Mapped["ShippingLabel"] = relationship()
