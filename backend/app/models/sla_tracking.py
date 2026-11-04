from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.shipping_label import ShippingLabel


class CalendarHoliday(Base):
    """Destination country public holidays cache and fallback table (RN-03)."""

    __tablename__ = "calendar_holidays"
    __table_args__ = (
        UniqueConstraint("country_code", "holiday_date", name="uq_calendar_holidays_country_date"),
        Index("ix_calendar_holidays_country_year", "country_code", "year"),
    )

    holiday_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    country_code: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    is_national: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ShipmentSlaTracking(Base):
    """Calculated SLA metrics, deadlines, and risk assessment for shipments (RN-03, RN-04)."""

    __tablename__ = "shipment_sla_tracking"
    __table_args__ = (
        UniqueConstraint("label_id", name="uq_shipment_sla_tracking_label_id"),
        Index("ix_shipment_sla_tracking_is_at_risk", "is_at_risk"),
        Index("ix_shipment_sla_tracking_sla_status", "sla_status"),
        Index("ix_shipment_sla_tracking_deadline_utc", "deadline_utc"),
    )

    tracking_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    label_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shipping_labels.label_id"), nullable=False
    )
    tracking_number: Mapped[str] = mapped_column(String, nullable=False, index=True)
    destination_country: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    shipment_type_code: Mapped[str] = mapped_column(String, nullable=False)
    sla_business_days: Mapped[int] = mapped_column(Integer, nullable=False)

    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Risk detection (RN-04)
    is_at_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    business_hours_remaining: Mapped[float | None] = mapped_column(nullable=True)
    exception_open_duration_hours: Mapped[float | None] = mapped_column(nullable=True)

    # Compliance status: PENDING, MET, BREACHED
    sla_status: Mapped[str] = mapped_column(String, default="PENDING", nullable=False)
    responsible_party: Mapped[str | None] = mapped_column(String, nullable=True)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    shipping_label: Mapped["ShippingLabel"] = relationship(back_populates="sla_tracking")
