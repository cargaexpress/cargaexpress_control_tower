from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.carrier import Carrier
    from app.models.shipping_label import ShippingLabel


class TrackingEvent(Base):
    """Historical tracking events recorded per shipping label for status auditing and exception timing."""

    __tablename__ = "tracking_events"
    __table_args__ = (
        Index("ix_tracking_events_tracking_number", "tracking_number"),
        Index("ix_tracking_events_label_id", "label_id"),
        Index("ix_tracking_events_canonical_status", "canonical_status"),
        Index("ix_tracking_events_event_timestamp", "event_timestamp"),
    )

    event_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    carrier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("carriers.carrier_id"), nullable=False
    )
    label_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("shipping_labels.label_id"), nullable=True
    )
    tracking_number: Mapped[str] = mapped_column(String, nullable=False)
    raw_status: Mapped[str] = mapped_column(String, nullable=False)
    canonical_status: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    carrier: Mapped["Carrier"] = relationship()
    shipping_label: Mapped["ShippingLabel | None"] = relationship()
