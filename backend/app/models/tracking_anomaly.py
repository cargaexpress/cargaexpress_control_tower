from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.carrier import Carrier
    from app.models.shipping_label import ShippingLabel


class TrackingAnomaly(Base):
    """Stores tracking event anomalies (such as RN-02 terminal state re-entry violations)."""

    __tablename__ = "tracking_anomalies"
    __table_args__ = (
        Index("ix_tracking_anomalies_tracking_number", "tracking_number"),
        Index("ix_tracking_anomalies_carrier_id", "carrier_id"),
        Index("ix_tracking_anomalies_created_at", "created_at"),
    )

    anomaly_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    carrier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("carriers.carrier_id"), nullable=False
    )
    tracking_number: Mapped[str] = mapped_column(String, nullable=False)
    label_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("shipping_labels.label_id"), nullable=True
    )
    current_status: Mapped[str] = mapped_column(String, nullable=False)
    attempted_status: Mapped[str] = mapped_column(String, nullable=False)
    raw_status: Mapped[str] = mapped_column(String, nullable=False)
    anomaly_type: Mapped[str] = mapped_column(
        String, nullable=False, default="TERMINAL_STATE_REVERSION"
    )
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    carrier: Mapped["Carrier"] = relationship()
    shipping_label: Mapped["ShippingLabel | None"] = relationship()
