from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Estados canónicos: el vocabulario único del sistema al que se traducen los
# estados que reporta cada transportadora. Se guardan como texto (no como enum de
# base de datos) para poder ampliarlos sin migración; la validación se hace en la API.
CANONICAL_STATUSES: tuple[str, ...] = (
    "CREATED",
    "PICKED_UP",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "DELIVERY_FAILED",
    "RETURNED",
    "CANCELLED",
    "EXCEPTION",
)


class StateMapping(Base):
    """Traducción configurable: estado de una transportadora -> estado canónico."""

    __tablename__ = "state_mapping"
    __table_args__ = (
        UniqueConstraint("carrier_id", "source_status", name="uq_state_mapping_carrier_source"),
    )

    mapping_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    carrier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("carriers.carrier_id"), nullable=False
    )
    source_status: Mapped[str] = mapped_column(String, nullable=False)
    canonical_status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    carrier: Mapped["Carrier"] = relationship()
