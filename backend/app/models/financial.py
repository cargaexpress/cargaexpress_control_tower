from datetime import date, datetime
from decimal import Decimal
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.brand import Brand
    from app.models.carrier import Carrier
    from app.models.order import Order
    from app.models.shipping_label import ShippingLabel


class ShipmentAttribution(Base):
    """Stores responsibility attribution for shipment delays and incidents (FR-04, BR-05).

    Responsible Parties:
    - DISTRIBUTION_CENTER: Delay occurring from order creation until dispatch.
    - CARRIER: Delay occurring from dispatch until final delivery.
    - CLIENT: Incident caused by incorrect delivery address (EXCEPTION: INCORRECT_ADDRESS).
    - UNDETERMINED: Insufficient tracking data/evidence to establish causality.
    """

    __tablename__ = "shipment_attributions"
    __table_args__ = (
        UniqueConstraint("label_id", name="uq_shipment_attributions_label_id"),
        Index("ix_shipment_attributions_responsible_party", "responsible_party"),
        Index("ix_shipment_attributions_carrier_id", "carrier_id"),
        Index("ix_shipment_attributions_tracking_number", "tracking_number"),
    )

    attribution_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    label_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shipping_labels.label_id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.order_id"), nullable=False)
    carrier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("carriers.carrier_id"), nullable=False
    )
    tracking_number: Mapped[str] = mapped_column(String, nullable=False)

    responsible_party: Mapped[str] = mapped_column(
        String, nullable=False
    )  # DISTRIBUTION_CENTER, CARRIER, CLIENT, UNDETERMINED
    incident_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # SLA_BREACH, ADDRESS_EXCEPTION, DISPATCH_DELAY, NORMAL_DELIVERY
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_details: Mapped[str | None] = mapped_column(Text, nullable=True)

    order_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    shipping_label: Mapped["ShippingLabel"] = relationship()
    order: Mapped["Order"] = relationship()
    carrier: Mapped["Carrier"] = relationship()


class FreightPenalty(Base):
    """Calculated financial penalties applied to freight costs (FR-04, BR-06).

    Penalty Rule:
    - Calculated as a percentage of the shipment freight cost.
    - Transferred to the carrier ONLY when the carrier is the responsible party.
    - Default documented tiers (TBD if contract overrides):
        1-2 days late -> 5%
        3-5 days late -> 10%
        6+ days late  -> 20%
    """

    __tablename__ = "freight_penalties"
    __table_args__ = (
        UniqueConstraint(
            "label_id", "incident_reference", name="uq_freight_penalties_label_incident"
        ),
        Index("ix_freight_penalties_carrier_id", "carrier_id"),
        Index("ix_freight_penalties_brand_id", "brand_id"),
        Index("ix_freight_penalties_settlement_id", "settlement_id"),
        Index("ix_freight_penalties_responsible_party", "responsible_party"),
    )

    penalty_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    label_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shipping_labels.label_id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.order_id"), nullable=False)
    carrier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("carriers.carrier_id"), nullable=False
    )
    brand_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("brands.brand_id"), nullable=False)
    settlement_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("financial_settlements.settlement_id"), nullable=True
    )

    tracking_number: Mapped[str] = mapped_column(String, nullable=False)
    incident_reference: Mapped[str] = mapped_column(String, nullable=False)
    responsible_party: Mapped[str] = mapped_column(String, nullable=False)

    freight_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    delay_business_days: Mapped[int] = mapped_column(Integer, nullable=False)
    penalty_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    penalty_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # Transferred to carrier only if responsible_party == "CARRIER"
    is_carrier_payable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Due to client (indemnity)
    is_client_owed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    contract_rule_applied: Mapped[str] = mapped_column(String, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    shipping_label: Mapped["ShippingLabel"] = relationship()
    order: Mapped["Order"] = relationship()
    carrier: Mapped["Carrier"] = relationship()
    brand: Mapped["Brand"] = relationship()
    settlement: Mapped["FinancialSettlement | None"] = relationship(back_populates="penalties")


class FinancialSettlement(Base):
    """Biweekly settlement period and netting calculation per carrier (FR-05, BR-08).

    Netting Rule:
    - Half-month calendar periods:
        Period 1: Days 1 to 15 of month
        Period 2: Days 16 to last day of month
    - Net amount = Client indemnities owed minus penalties recoverable from carrier.
    """

    __tablename__ = "financial_settlements"
    __table_args__ = (
        UniqueConstraint(
            "carrier_id", "period_code", name="uq_financial_settlements_carrier_period"
        ),
        Index("ix_financial_settlements_carrier_id", "carrier_id"),
        Index("ix_financial_settlements_period_code", "period_code"),
        Index("ix_financial_settlements_status", "status"),
    )

    settlement_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    carrier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("carriers.carrier_id"), nullable=False
    )
    period_code: Mapped[str] = mapped_column(
        String, nullable=False
    )  # e.g. "2026-11-H1", "2026-11-H2"
    period_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_end_date: Mapped[date] = mapped_column(Date, nullable=False)

    total_penalties_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_freight_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    total_owed_to_clients: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    total_recoverable_from_carrier: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    net_settlement_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String, default="DRAFT", nullable=False
    )  # DRAFT, CLOSED, SETTLED
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    carrier: Mapped["Carrier"] = relationship()
    penalties: Mapped[list["FreightPenalty"]] = relationship(back_populates="settlement")
    ledger_entries: Mapped[list["FinancialLedgerEntry"]] = relationship(back_populates="settlement")


class FinancialLedgerEntry(Base):
    """Detailed audit trail and double-entry/movement record for financial reconciliation."""

    __tablename__ = "financial_ledger_entries"
    __table_args__ = (
        Index("ix_financial_ledger_entries_settlement_id", "settlement_id"),
        Index("ix_financial_ledger_entries_carrier_id", "carrier_id"),
        Index("ix_financial_ledger_entries_entry_type", "entry_type"),
    )

    entry_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    settlement_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("financial_settlements.settlement_id", ondelete="CASCADE"),
        nullable=False,
    )
    carrier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("carriers.carrier_id"), nullable=False
    )
    brand_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("brands.brand_id"), nullable=True
    )
    penalty_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("freight_penalties.penalty_id"), nullable=True
    )

    entry_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # CLIENT_INDEMNITY_PAYABLE, CARRIER_PENALTY_RECEIVABLE, NET_SETTLEMENT
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), default="COP", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    settlement: Mapped["FinancialSettlement"] = relationship(back_populates="ledger_entries")
    carrier: Mapped["Carrier"] = relationship()
    penalty: Mapped["FreightPenalty | None"] = relationship()
