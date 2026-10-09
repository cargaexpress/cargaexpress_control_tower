from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# This shared catalog is enforced in both API validation and the database.
# Strings plus a CHECK constraint avoid a DB enum migration for catalog changes.
# Estados canónicos: vocabulario único para traducir los estados de cada
# transportadora. Se guarda como texto para ampliar el catálogo sin migrar un enum;
# la API y una restricción CHECK de la base de datos validan los valores permitidos.
CANONICAL_STATUSES: tuple[str, ...] = (
    "CREATED",
    "PICKED_UP",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "EXCEPTION",
    "DELIVERED",
    "RETURNED",
    "LOST_OR_DAMAGED",
)

_CANONICAL_STATUS_VALUES = ", ".join(f"'{status}'" for status in CANONICAL_STATUSES)


class StateMapping(Base):
    """Configurable carrier-status translation.

    Traducción configurable de estados de transportadoras.
    """

    __tablename__ = "state_mapping"
    __table_args__ = (
        # One raw status has one meaning per carrier; the CHECK protects direct DB writes too.
        # Un estado original tiene un significado por transportadora; CHECK protege escrituras SQL.
        UniqueConstraint("carrier_id", "raw_status", name="uq_state_mapping_carrier_raw_status"),
        CheckConstraint(
            f"canonical_status IN ({_CANONICAL_STATUS_VALUES})",
            name="ck_state_mapping_canonical_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    carrier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("carriers.carrier_id"), nullable=False
    )
    raw_status: Mapped[str] = mapped_column(String, nullable=False)
    canonical_status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    carrier: Mapped["Carrier"] = relationship()
