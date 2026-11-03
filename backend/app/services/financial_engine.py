import calendar
import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import (
    FinancialLedgerEntry,
    FinancialSettlement,
    FreightPenalty,
    ShipmentAttribution,
)
from app.models.shipping_label import ShippingLabel
from app.models.sla_tracking import ShipmentSlaTracking
from app.models.tracking_anomaly import TrackingAnomaly
from app.services.sla_engine import SlaEngineService

logger = logging.getLogger("cargaexpress.financial_engine")

# Documented contractual delay penalty tiers (from seed data / business rules BR-06)
# Marked TBD for future customized contractual Excel overrides
DEFAULT_PENALTY_TIERS = [
    (1, 2, Decimal("5.00")),  # 1-2 days late -> 5%
    (3, 5, Decimal("10.00")),  # 3-5 days late -> 10%
    (6, 9999, Decimal("20.00")),  # 6+ days late -> 20%
]

# Max normal duration for DC picking and dispatch (hours before DC is held responsible)
DC_MAX_DISPATCH_HOURS = 48.0


class FinancialEngineService:
    """Core domain service for responsibility attribution, penalty calculation, and biweekly settlements.

    Implements:
    - BR-05: Responsibility Attribution (DC: creation->dispatch, Carrier: dispatch->delivery, Client: wrong address)
    - BR-06: Freight Penalty Calculation (% of freight, transferred to carrier ONLY if responsible)
    - BR-08: Biweekly Settlements and Financial Netting
    """

    def __init__(self, sla_engine: SlaEngineService | None = None) -> None:
        self.sla_engine = sla_engine or SlaEngineService()

    # =========================================================================
    # 1. Responsibility Attribution Engine (BR-05)
    # =========================================================================

    async def attribute_shipment_responsibility(
        self,
        db: AsyncSession,
        label: ShippingLabel,
        current_time_utc: datetime | None = None,
    ) -> ShipmentAttribution:
        """Determine and persist responsibility attribution for delays or incidents on a shipment."""
        now = current_time_utc or datetime.now(UTC)
        # Ensure order is loaded in async context
        order = None
        if "order" in label.__dict__ and label.order:
            order = label.order
        elif label.order_id:
            from app.models.order import Order

            stmt_o = select(Order).where(Order.order_id == label.order_id)
            res_o = await db.execute(stmt_o)
            order = res_o.scalar_one_or_none()
            label.order = order

        if not order:
            raise ValueError(f"Shipping label {label.label_id} has no associated order.")

        order_created_at = order.created_at
        if order_created_at and order_created_at.tzinfo is None:
            order_created_at = order_created_at.replace(tzinfo=UTC)
        # Retrieve dispatched_at from dispatch table directly using explicit query to avoid lazy load issues
        dispatched_at = None
        if label.dispatch_id:
            from app.models.dispatch import Dispatch

            stmt_d = select(Dispatch.dispatched_at).where(Dispatch.dispatch_id == label.dispatch_id)
            res_d = await db.execute(stmt_d)
            dispatched_at = res_d.scalar_one_or_none()
        elif "dispatch" in label.__dict__ and label.dispatch:
            dispatched_at = label.dispatch.dispatched_at
        delivered_at = now if label.status.upper() == "DELIVERED" else None

        # Check existing SLA tracking for deadline
        stmt_sla = select(ShipmentSlaTracking).where(ShipmentSlaTracking.label_id == label.label_id)
        res_sla = await db.execute(stmt_sla)
        sla_record = res_sla.scalar_one_or_none()

        sla_deadline = sla_record.deadline_utc if sla_record else None
        if not sla_deadline and dispatched_at:
            _, sla_deadline = await self.sla_engine.calculate_delivery_deadline(
                db=db,
                dispatched_at_utc=dispatched_at,
                sla_business_days=3,
                destination_country=order.destination_country,
            )

        # Check for address-related exceptions or anomalies (Client responsibility)
        stmt_anomaly = select(TrackingAnomaly).where(
            TrackingAnomaly.label_id == label.label_id,
        )
        res_anom = await db.execute(stmt_anomaly)
        anomalies = res_anom.scalars().all()

        is_address_exception = any(
            "ADDRESS" in (a.details or "").upper()
            or "DIRECCION" in (a.details or "").upper()
            or "ADDRESS" in a.raw_status.upper()
            or "DIRECCION" in a.raw_status.upper()
            for a in anomalies
        ) or (
            label.status.upper() == "EXCEPTION"
            and "ADDRESS" in (order.destination_region or "").upper()
        )

        responsible_party: str
        incident_type: str
        reason: str
        evidence: dict[str, object] = {
            "order_created_at": order_created_at.isoformat() if order_created_at else None,
            "dispatched_at": dispatched_at.isoformat() if dispatched_at else None,
            "delivered_at": delivered_at.isoformat() if delivered_at else None,
            "sla_deadline": sla_deadline.isoformat() if sla_deadline else None,
        }

        # --- Rule Attribution Logic ---
        if is_address_exception:
            responsible_party = "CLIENT"
            incident_type = "ADDRESS_EXCEPTION"
            reason = (
                "Delivery failure or delay caused by incorrect address supplied by client/brand."
            )
            evidence["cause"] = "INCORRECT_ADDRESS"

        elif not dispatched_at:
            # Not dispatched yet
            hours_since_creation = (now - order_created_at).total_seconds() / 3600.0
            evidence["hours_in_dc"] = round(hours_since_creation, 2)
            if hours_since_creation > DC_MAX_DISPATCH_HOURS:
                responsible_party = "DISTRIBUTION_CENTER"
                incident_type = "DISPATCH_DELAY"
                reason = f"Order remained in distribution center for {hours_since_creation:.1f} hours without dispatch."
            else:
                responsible_party = "UNDETERMINED"
                incident_type = "NORMAL_PROCESSING"
                reason = "Order is currently within normal distribution center fulfillment window."

        elif sla_deadline and (
            (delivered_at and delivered_at > sla_deadline)
            or (not delivered_at and now > sla_deadline)
        ):
            # SLA breached after dispatch -> Carrier responsibility
            responsible_party = "CARRIER"
            incident_type = "SLA_BREACH"
            delay_hours = ((delivered_at or now) - sla_deadline).total_seconds() / 3600.0
            evidence["delay_hours"] = round(delay_hours, 2)
            reason = f"Shipment exceeded SLA delivery deadline by {delay_hours:.1f} hours under carrier transit."

        elif label.status.upper() == "DELIVERED":
            responsible_party = "CARRIER"
            incident_type = "NORMAL_DELIVERY"
            reason = "Shipment delivered on time within SLA contract terms."

        else:
            responsible_party = "UNDETERMINED"
            incident_type = "IN_TRANSIT"
            reason = "Shipment in transit within acceptable SLA deadlines."

        # Upsert attribution record
        stmt_attr = select(ShipmentAttribution).where(
            ShipmentAttribution.label_id == label.label_id
        )
        res_attr = await db.execute(stmt_attr)
        attr = res_attr.scalar_one_or_none()

        if not attr:
            attr = ShipmentAttribution(
                label_id=label.label_id,
                order_id=order.order_id,
                carrier_id=label.carrier_id,
                tracking_number=label.tracking_number,
                responsible_party=responsible_party,
                incident_type=incident_type,
                reason=reason,
                evidence_details=json.dumps(evidence),
                order_created_at=order_created_at,
                dispatched_at=dispatched_at,
                delivered_at=delivered_at,
                sla_deadline=sla_deadline,
            )
            db.add(attr)
        else:
            attr.responsible_party = responsible_party
            attr.incident_type = incident_type
            attr.reason = reason
            attr.evidence_details = json.dumps(evidence)
            attr.dispatched_at = dispatched_at
            attr.delivered_at = delivered_at
            attr.sla_deadline = sla_deadline

        await db.flush()
        return attr

    # =========================================================================
    # 2. Freight Penalty Calculation Engine (BR-06)
    # =========================================================================

    def resolve_penalty_percentage(self, delay_days: int) -> tuple[Decimal, str]:
        """Resolve penalty percentage based on delay business days.

        Returns (percentage, rule_applied).
        """
        if delay_days <= 0:
            return Decimal("0.00"), "NO_DELAY"

        for min_days, max_days, pct in DEFAULT_PENALTY_TIERS:
            if min_days <= delay_days <= max_days:
                return pct, f"CONTRACT_TIER_{min_days}_{max_days}_DAYS_{pct}%"

        return Decimal("20.00"), "CONTRACT_TIER_MAX_20%"

    async def calculate_freight_penalty(
        self,
        db: AsyncSession,
        label: ShippingLabel,
        current_time_utc: datetime | None = None,
    ) -> FreightPenalty | None:
        """Calculate freight penalty for a delayed shipment.

        Rules:
        - Must be delayed past SLA deadline.
        - Calculated as % of freight cost.
        - Transferred to carrier ONLY if responsible_party == 'CARRIER'.
        - Prevents duplicate penalties for the same shipment.
        """
        now = current_time_utc or datetime.now(UTC)

        # Ensure order is loaded in async context
        order = None
        if "order" in label.__dict__ and label.order:
            order = label.order
        elif label.order_id:
            from app.models.order import Order

            stmt_o = select(Order).where(Order.order_id == label.order_id)
            res_o = await db.execute(stmt_o)
            order = res_o.scalar_one_or_none()
            label.order = order

        if not order:
            return None

        # 1. Attribute responsibility first
        attribution = await self.attribute_shipment_responsibility(db, label, current_time_utc=now)

        # 2. Check if delay or DC breach occurred
        sla_deadline = attribution.sla_deadline
        delivered_at = attribution.delivered_at or (
            now if label.status.upper() == "DELIVERED" else None
        )
        effective_completion = delivered_at or now

        # If not dispatched yet but DC delayed
        if attribution.responsible_party == "DISTRIBUTION_CENTER":
            # Calculate days delayed in DC past normal 48h
            hours_in_dc = (now - attribution.order_created_at).total_seconds() / 3600.0
            delay_days = max(1, int((hours_in_dc - DC_MAX_DISPATCH_HOURS) // 24) + 1)
        elif not sla_deadline or effective_completion <= sla_deadline:
            # No SLA delay breached
            return None
        else:
            # Calculate delay in business days
            delay_days = max(1, (effective_completion.date() - sla_deadline.date()).days)
        pct, contract_rule = self.resolve_penalty_percentage(delay_days)

        freight_cost = Decimal(str(order.freight_value))
        penalty_amount = (freight_cost * (pct / Decimal("100.00"))).quantize(Decimal("0.01"))

        # Rule BR-06: Transfer to carrier ONLY if carrier is responsible
        is_carrier_responsible = attribution.responsible_party == "CARRIER"
        is_carrier_payable = is_carrier_responsible
        is_client_owed = attribution.responsible_party in {"CARRIER", "DISTRIBUTION_CENTER"}

        incident_ref = f"DELAY_DAYS_{delay_days}"

        # Prevent duplicate penalty
        stmt = select(FreightPenalty).where(
            FreightPenalty.label_id == label.label_id,
            FreightPenalty.incident_reference == incident_ref,
        )
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            return existing

        penalty = FreightPenalty(
            label_id=label.label_id,
            order_id=order.order_id,
            carrier_id=label.carrier_id,
            brand_id=order.brand_id,
            tracking_number=label.tracking_number,
            incident_reference=incident_ref,
            responsible_party=attribution.responsible_party,
            freight_amount=freight_cost,
            delay_business_days=delay_days,
            penalty_percentage=pct,
            penalty_amount=penalty_amount,
            is_carrier_payable=is_carrier_payable,
            is_client_owed=is_client_owed,
            contract_rule_applied=contract_rule,
        )
        db.add(penalty)
        await db.flush()
        return penalty

    # =========================================================================
    # 3. Biweekly Settlement Engine (FR-05, BR-08)
    # =========================================================================

    def compute_half_month_period(self, year: int, month: int, half: int) -> tuple[str, date, date]:
        """Compute period code, start date, and end date for calendar half-month."""
        _, last_day = calendar.monthrange(year, month)
        if half == 1:
            period_code = f"{year:04d}-{month:02d}-H1"
            start_d = date(year, month, 1)
            end_d = date(year, month, 15)
        else:
            period_code = f"{year:04d}-{month:02d}-H2"
            start_d = date(year, month, 16)
            end_d = date(year, month, last_day)

        return period_code, start_d, end_d

    async def generate_biweekly_settlement(
        self,
        db: AsyncSession,
        carrier_id: int,
        year: int,
        month: int,
        half: int,
        notes: str | None = None,
    ) -> FinancialSettlement:
        """Generate biweekly settlement and calculate netting for a carrier over a calendar half-month.

        Netting formula (BR-08):
        - total_owed_to_clients: Sum of penalties where is_client_owed=True.
        - total_recoverable_from_carrier: Sum of penalties where is_carrier_payable=True.
        - net_settlement_amount: total_owed_to_clients - total_recoverable_from_carrier.
        """
        period_code, start_date, end_date = self.compute_half_month_period(year, month, half)

        # Check existing settlement for carrier and period
        stmt = select(FinancialSettlement).where(
            FinancialSettlement.carrier_id == carrier_id,
            FinancialSettlement.period_code == period_code,
        )
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing:
            return existing

        # Convert date range to UTC datetime boundaries
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)

        # Select all unassigned penalties for this carrier in this period
        stmt_penalties = select(FreightPenalty).where(
            FreightPenalty.carrier_id == carrier_id,
            FreightPenalty.settlement_id.is_(None),
            FreightPenalty.calculated_at >= start_dt,
            FreightPenalty.calculated_at < end_dt,
        )
        res_p = await db.execute(stmt_penalties)
        penalties = res_p.scalars().all()

        total_freight = sum((p.freight_amount for p in penalties), Decimal("0.00"))
        total_owed_clients = sum(
            (p.penalty_amount for p in penalties if p.is_client_owed), Decimal("0.00")
        )
        total_recoverable_carrier = sum(
            (p.penalty_amount for p in penalties if p.is_carrier_payable), Decimal("0.00")
        )
        net_amount = total_owed_clients - total_recoverable_carrier

        settlement = FinancialSettlement(
            carrier_id=carrier_id,
            period_code=period_code,
            period_start_date=start_date,
            period_end_date=end_date,
            total_penalties_count=len(penalties),
            total_freight_amount=total_freight,
            total_owed_to_clients=total_owed_clients,
            total_recoverable_from_carrier=total_recoverable_carrier,
            net_settlement_amount=net_amount,
            status="CLOSED",
            notes=notes or f"Biweekly settlement for {period_code}",
            closed_at=datetime.now(UTC),
        )
        db.add(settlement)
        await db.flush()

        # Link penalties and create audit ledger movements
        for p in penalties:
            p.settlement_id = settlement.settlement_id

            # Ledger entry for client indemnity
            if p.is_client_owed:
                ledger_client = FinancialLedgerEntry(
                    settlement_id=settlement.settlement_id,
                    carrier_id=carrier_id,
                    brand_id=p.brand_id,
                    penalty_id=p.penalty_id,
                    entry_type="CLIENT_INDEMNITY_PAYABLE",
                    amount=p.penalty_amount,
                    currency="COP",
                    description=f"Indemnity payable to client for delayed tracking {p.tracking_number} ({p.delay_business_days} days late).",
                )
                db.add(ledger_client)

            # Ledger entry for carrier penalty
            if p.is_carrier_payable:
                ledger_carrier = FinancialLedgerEntry(
                    settlement_id=settlement.settlement_id,
                    carrier_id=carrier_id,
                    brand_id=p.brand_id,
                    penalty_id=p.penalty_id,
                    entry_type="CARRIER_PENALTY_RECEIVABLE",
                    amount=p.penalty_amount,
                    currency="COP",
                    description=f"Penalty recoverable from carrier {carrier_id} for shipment {p.tracking_number}.",
                )
                db.add(ledger_carrier)

        # Master Net Settlement movement
        master_ledger = FinancialLedgerEntry(
            settlement_id=settlement.settlement_id,
            carrier_id=carrier_id,
            brand_id=None,
            penalty_id=None,
            entry_type="NET_SETTLEMENT",
            amount=net_amount,
            currency="COP",
            description=f"Net settlement amount for period {period_code}: owed to clients {total_owed_clients} minus recoverable {total_recoverable_carrier}.",
        )
        db.add(master_ledger)
        await db.flush()

        return settlement
