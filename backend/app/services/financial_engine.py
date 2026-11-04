import calendar
import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import (
    FinancialLedgerEntry,
    FinancialSettlement,
    FreightPenalty,
    ShipmentAttribution,
    UniversalPenaltyConfig,
)
from app.models.shipping_label import ShippingLabel
from app.models.sla_tracking import ShipmentSlaTracking
from app.models.tracking_anomaly import TrackingAnomaly
from app.services.sla_engine import SlaEngineService

logger = logging.getLogger("cargaexpress.financial_engine")

# The five universal progressive penalty scale levels (Phase 4)
UNIVERSAL_DELAY_LEVELS = ("NO_DELAY", "LOW", "MODERATE", "HIGH", "CRITICAL")


class FinancialEngineService:
    """Core domain service for responsibility attribution, progressive penalty calculation,
    and biweekly financial settlements (Phase 4).

    Adheres strictly to:
    - Universal Progressive Penalty Scale (NO_DELAY, LOW, MODERATE, HIGH, CRITICAL)
    - Python Decimal arithmetic for all monetary calculations
    - Configurable delay thresholds and percentage caps without hardcoded assumptions
    - Responsibility Attribution (Carrier, Client, DC, or Undetermined)
    - Biweekly settlements in separate balances (client liabilities vs carrier recoverables)
      marked PENDING_VALIDATION without unauthorized netting.
    """

    def __init__(self, sla_engine: SlaEngineService | None = None) -> None:
        self.sla_engine = sla_engine or SlaEngineService()

    # =========================================================================
    # 1. Responsibility Attribution Engine (FR-04, BR-05)
    # =========================================================================

    async def attribute_shipment_responsibility(
        self,
        db: AsyncSession,
        label: ShippingLabel,
        current_time_utc: datetime | None = None,
        dc_dispatch_sla_hours: float | None = None,
    ) -> ShipmentAttribution:
        """Determine and persist responsibility attribution for shipment delays or incidents.

        Rules:
        - Incorrect delivery address exception -> CLIENT.
        - SLA breached after dispatch under carrier custody -> CARRIER.
        - Delivered on time -> CARRIER (NORMAL_DELIVERY).
        - Order created but not dispatched:
            If dc_dispatch_sla_hours is explicitly configured and exceeded -> DISTRIBUTION_CENTER.
            Otherwise -> UNDETERMINED (pending approved warehouse dispatch policy).
        - Unclear causality / insufficient evidence -> UNDETERMINED.
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
            if order is not None:
                label.order = order

        if not order:
            raise ValueError(f"Shipping label {label.label_id} has no associated order.")

        order_created_at = order.created_at
        if order_created_at and order_created_at.tzinfo is None:
            order_created_at = order_created_at.replace(tzinfo=UTC)

        # Retrieve dispatched_at from dispatch table
        dispatched_at = None
        if label.dispatch_id:
            from app.models.dispatch import Dispatch

            stmt_d = select(Dispatch.dispatched_at).where(Dispatch.dispatch_id == label.dispatch_id)
            res_d = await db.execute(stmt_d)
            dispatched_at = res_d.scalar_one_or_none()
        elif "dispatch" in label.__dict__ and label.dispatch:
            dispatched_at = label.dispatch.dispatched_at

        delivered_at = now if label.status.upper() == "DELIVERED" else None
        if dispatched_at and dispatched_at.tzinfo is None:
            dispatched_at = dispatched_at.replace(tzinfo=UTC)
        if delivered_at and delivered_at.tzinfo is None:
            delivered_at = delivered_at.replace(tzinfo=UTC)

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
        if sla_deadline and sla_deadline.tzinfo is None:
            sla_deadline = sla_deadline.replace(tzinfo=UTC)

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
            # Order created but not yet dispatched
            hours_since_creation = (
                (now - order_created_at).total_seconds() / 3600.0 if order_created_at else 0.0
            )
            evidence["hours_in_dc"] = round(hours_since_creation, 2)
            if dc_dispatch_sla_hours is not None and hours_since_creation > dc_dispatch_sla_hours:
                responsible_party = "DISTRIBUTION_CENTER"
                incident_type = "DISPATCH_DELAY"
                reason = (
                    f"Order remained in distribution center for {hours_since_creation:.1f} hours, "
                    f"exceeding approved dispatch threshold ({dc_dispatch_sla_hours:.1f} hours)."
                )
            else:
                responsible_party = "UNDETERMINED"
                incident_type = "PENDING_DISPATCH"
                reason = (
                    "Order created but not dispatched. Distribution center dispatch SLA threshold "
                    "is pending approved business configuration."
                )

        elif sla_deadline and (
            (delivered_at and delivered_at > sla_deadline)
            or (not delivered_at and now > sla_deadline)
        ):
            # SLA breached after dispatch -> Carrier custody
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
                order_created_at=order_created_at or now,
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
    # 2. Universal Progressive Penalty Scale Engine (FR-04, BR-06)
    # =========================================================================

    @staticmethod
    def calculate_penalty_amounts(
        freight_amount: Decimal,
        penalty_percentage: Decimal,
        maximum_cap_percentage: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal]:
        """Perform exact Decimal financial penalty calculation with maximum percentage cap.

        Formula:
        base_penalty = freight_amount * (penalty_percentage / 100)
        maximum_penalty = freight_amount * (maximum_cap_percentage / 100)
        final_penalty = min(base_penalty, maximum_penalty)

        Rounds results consistently to 2 decimal places using ROUND_HALF_UP.
        No floating-point operations allowed.
        """
        two_places = Decimal("0.01")
        pct_factor = penalty_percentage / Decimal("100")
        cap_factor = maximum_cap_percentage / Decimal("100")

        base_penalty = (freight_amount * pct_factor).quantize(two_places, rounding=ROUND_HALF_UP)
        max_penalty = (freight_amount * cap_factor).quantize(two_places, rounding=ROUND_HALF_UP)
        final_penalty = min(base_penalty, max_penalty)
        return base_penalty, max_penalty, final_penalty

    async def count_delay_business_days(
        self,
        db: AsyncSession,
        deadline_utc: datetime,
        actual_utc: datetime,
        destination_country: str,
    ) -> int:
        """Count business days elapsed past deadline_utc in destination country.

        Integrates with SlaEngineService: excludes Sundays and Nager.Date holidays.
        """
        if actual_utc <= deadline_utc:
            return 0

        tz = self.sla_engine.get_country_timezone(destination_country)
        deadline_local = deadline_utc.astimezone(tz)
        actual_local = actual_utc.astimezone(tz)

        if actual_local.date() <= deadline_local.date():
            return 0

        delay_days = 0
        curr = deadline_local.date() + timedelta(days=1)
        while curr <= actual_local.date():
            if await self.sla_engine.is_business_day(db, curr, destination_country):
                delay_days += 1
            curr += timedelta(days=1)
        return delay_days

    async def get_or_initialize_penalty_configs(
        self,
        db: AsyncSession,
        version: str = "v1.0",
    ) -> list[UniversalPenaltyConfig]:
        """Retrieve active progressive penalty configurations.

        If unconfigured, seeds the 5 required levels in PENDING_APPROVAL status
        without assuming or inventing business percentages.
        """
        stmt = (
            select(UniversalPenaltyConfig)
            .where(
                UniversalPenaltyConfig.version == version,
                UniversalPenaltyConfig.is_active.is_(True),
            )
            .order_by(UniversalPenaltyConfig.config_id)
        )
        res = await db.execute(stmt)
        configs = list(res.scalars().all())
        if configs:
            return configs

        # Seed unapproved scaffolding for the 5 universal levels
        today = date.today()
        initial_scaffolding = [
            ("NO_DELAY", 0, 0, Decimal("0.00"), Decimal("0.00"), "APPROVED"),
            ("LOW", None, None, None, None, "PENDING_APPROVAL"),
            ("MODERATE", None, None, None, None, "PENDING_APPROVAL"),
            ("HIGH", None, None, None, None, "PENDING_APPROVAL"),
            ("CRITICAL", None, None, None, None, "PENDING_APPROVAL"),
        ]
        created = []
        for level, min_d, max_d, pct, cap, status in initial_scaffolding:
            cfg = UniversalPenaltyConfig(
                version=version,
                delay_level=level,
                min_delay_days=min_d,
                max_delay_days=max_d,
                penalty_percentage=pct,
                maximum_cap_percentage=cap,
                effective_date=today,
                is_active=True,
                approval_status=status,
            )
            db.add(cfg)
            created.append(cfg)
        await db.flush()
        return created

    async def resolve_penalty_tier(
        self,
        db: AsyncSession,
        delay_business_days: int,
        version: str = "v1.0",
    ) -> tuple[str, UniversalPenaltyConfig | None]:
        """Resolve the universal penalty level and active configuration entry.

        Returns (delay_level, matching_config_or_none).
        """
        if delay_business_days <= 0:
            configs = await self.get_or_initialize_penalty_configs(db, version=version)
            no_delay_cfg = next((c for c in configs if c.delay_level == "NO_DELAY"), None)
            return "NO_DELAY", no_delay_cfg

        configs = await self.get_or_initialize_penalty_configs(db, version=version)
        for cfg in configs:
            if cfg.delay_level == "NO_DELAY":
                continue
            if (
                cfg.min_delay_days is not None
                and cfg.min_delay_days <= delay_business_days
                and (cfg.max_delay_days is None or delay_business_days <= cfg.max_delay_days)
            ):
                return cfg.delay_level, cfg

        # Delay exists but thresholds are not configured or matching
        return "PENDING_CLASSIFICATION", None

    async def calculate_freight_penalty(
        self,
        db: AsyncSession,
        label: ShippingLabel,
        current_time_utc: datetime | None = None,
        config_version: str = "v1.0",
        dc_dispatch_sla_hours: float | None = None,
    ) -> FreightPenalty | None:
        """Calculate progressive freight penalty for a shipment.

        Adheres strictly to:
        - Universal 5-level scale.
        - Decimal calculation with maximum percentage cap.
        - If configuration is PENDING_APPROVAL: record penalty with calculation_status="PENDING_APPROVAL",
          no definitive charge generated (penalty_amount=None), not payable.
        - If responsibility is UNDETERMINED: no definitive charge generated.
        - Recoverable from carrier (is_carrier_payable=True) ONLY when carrier responsibility is established
          under approved rules and calculation is approved.
        """
        now = current_time_utc or datetime.now(UTC)

        # Load order in async context
        order = None
        if "order" in label.__dict__ and label.order:
            order = label.order
        elif label.order_id:
            from app.models.order import Order

            stmt_o = select(Order).where(Order.order_id == label.order_id)
            res_o = await db.execute(stmt_o)
            order = res_o.scalar_one_or_none()
            if order is not None:
                label.order = order

        if not order:
            return None

        # 1. Attribute responsibility
        attribution = await self.attribute_shipment_responsibility(
            db, label, current_time_utc=now, dc_dispatch_sla_hours=dc_dispatch_sla_hours
        )

        # 2. Determine business-day delay
        sla_deadline = attribution.sla_deadline
        effective_completion = attribution.delivered_at or (
            now if label.status.upper() == "DELIVERED" else now
        )
        if effective_completion and effective_completion.tzinfo is None:
            effective_completion = effective_completion.replace(tzinfo=UTC)
        if sla_deadline and sla_deadline.tzinfo is None:
            sla_deadline = sla_deadline.replace(tzinfo=UTC)

        delay_days = 0
        if sla_deadline:
            delay_days = await self.count_delay_business_days(
                db=db,
                deadline_utc=sla_deadline,
                actual_utc=effective_completion,
                destination_country=order.destination_country,
            )

        # 3. Resolve universal penalty level and configuration
        delay_level, config = await self.resolve_penalty_tier(
            db, delay_days, version=config_version
        )

        freight_cost = Decimal(str(order.freight_value))
        incident_ref = f"DELAY_DAYS_{delay_days}_{delay_level}"

        # 4. Determine financial charge based on approval status and responsibility
        calculation_status: str
        penalty_percentage: Decimal | None = None
        base_penalty: Decimal | None = None
        max_penalty: Decimal | None = None
        final_penalty: Decimal | None = None
        is_carrier_payable: bool = False
        is_client_owed: bool = False
        contract_rule: str

        if attribution.responsible_party == "UNDETERMINED":
            # Responsibility undetermined -> no definitive financial charge
            calculation_status = "UNDETERMINED_RESPONSIBILITY"
            penalty_percentage = None
            base_penalty = None
            max_penalty = None
            final_penalty = None
            is_carrier_payable = False
            is_client_owed = False
            contract_rule = f"UNIVERSAL_SCALE_{delay_level}_UNDETERMINED_RESPONSIBILITY"

        elif delay_level == "NO_DELAY":
            calculation_status = "NO_DELAY"
            penalty_percentage = Decimal("0.00")
            base_penalty = Decimal("0.00")
            max_penalty = Decimal("0.00")
            final_penalty = Decimal("0.00")
            is_carrier_payable = False
            is_client_owed = False
            contract_rule = "UNIVERSAL_SCALE_NO_DELAY"

        elif (
            config is not None
            and config.approval_status == "APPROVED"
            and config.penalty_percentage is not None
            and config.maximum_cap_percentage is not None
        ):
            # Approved configuration -> calculate definitive monetary amounts
            base_penalty, max_penalty, final_penalty = self.calculate_penalty_amounts(
                freight_amount=freight_cost,
                penalty_percentage=config.penalty_percentage,
                maximum_cap_percentage=config.maximum_cap_percentage,
            )
            calculation_status = "APPROVED"
            penalty_percentage = config.penalty_percentage
            # Carrier recoverable only when Carrier is responsible
            is_carrier_payable = attribution.responsible_party == "CARRIER"
            is_client_owed = attribution.responsible_party in {"CARRIER", "DISTRIBUTION_CENTER"}
            contract_rule = (
                f"UNIVERSAL_SCALE_{delay_level}_{config.penalty_percentage}%_"
                f"CAP_{config.maximum_cap_percentage}%_APPROVED"
            )

        else:
            # Unapproved configuration -> do not generate definitive charges
            calculation_status = "PENDING_APPROVAL"
            penalty_percentage = config.penalty_percentage if config else None
            base_penalty = None
            max_penalty = None
            final_penalty = None
            is_carrier_payable = False
            is_client_owed = False
            contract_rule = f"UNIVERSAL_SCALE_{delay_level}_PENDING_APPROVAL"

        # Check existing penalty record for idempotency
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
            delay_level=delay_level,
            calculation_status=calculation_status,
            penalty_percentage=penalty_percentage,
            base_penalty_amount=base_penalty,
            maximum_penalty_amount=max_penalty,
            penalty_amount=final_penalty,
            is_carrier_payable=is_carrier_payable,
            is_client_owed=is_client_owed,
            contract_rule_applied=contract_rule,
            calculated_at=now,
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
        """Generate biweekly settlement for a carrier over a calendar half-month.

        Preserves:
        - Separate balances for client liabilities (total_owed_to_clients) and
          carrier recoverables (total_recoverable_from_carrier).
        - Status is PENDING_VALIDATION until a netting formula is approved.
        - net_settlement_amount is set to None (no unauthorized netting).
        - Detailed double-entry movements recorded in the financial ledger.
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
        # Sum approved definitive amounts only
        total_owed_clients = sum(
            (
                p.penalty_amount
                for p in penalties
                if p.is_client_owed and p.penalty_amount is not None
            ),
            Decimal("0.00"),
        )
        total_recoverable_carrier = sum(
            (
                p.penalty_amount
                for p in penalties
                if p.is_carrier_payable and p.penalty_amount is not None
            ),
            Decimal("0.00"),
        )

        settlement = FinancialSettlement(
            carrier_id=carrier_id,
            period_code=period_code,
            period_start_date=start_date,
            period_end_date=end_date,
            total_penalties_count=len(penalties),
            total_freight_amount=total_freight,
            total_owed_to_clients=total_owed_clients,
            total_recoverable_from_carrier=total_recoverable_carrier,
            net_settlement_amount=None,  # Pending financial approval
            status="PENDING_VALIDATION",
            notes=(
                notes
                or f"Biweekly settlement for {period_code}. Netting formula pending validation."
            ),
            closed_at=None,
        )
        db.add(settlement)
        await db.flush()

        # Link penalties and create audit ledger movements for approved amounts
        for p in penalties:
            p.settlement_id = settlement.settlement_id

            if p.is_client_owed and p.penalty_amount is not None:
                ledger_client = FinancialLedgerEntry(
                    settlement_id=settlement.settlement_id,
                    carrier_id=carrier_id,
                    brand_id=p.brand_id,
                    penalty_id=p.penalty_id,
                    entry_type="CLIENT_INDEMNITY_PAYABLE",
                    amount=p.penalty_amount,
                    currency="COP",
                    description=(
                        f"Indemnity payable to client for delayed tracking {p.tracking_number} "
                        f"({p.delay_business_days} business days late, level {p.delay_level})."
                    ),
                )
                db.add(ledger_client)

            if p.is_carrier_payable and p.penalty_amount is not None:
                ledger_carrier = FinancialLedgerEntry(
                    settlement_id=settlement.settlement_id,
                    carrier_id=carrier_id,
                    brand_id=p.brand_id,
                    penalty_id=p.penalty_id,
                    entry_type="CARRIER_PENALTY_RECEIVABLE",
                    amount=p.penalty_amount,
                    currency="COP",
                    description=(
                        f"Penalty recoverable from carrier {carrier_id} for shipment {p.tracking_number} "
                        f"({p.delay_business_days} business days late, level {p.delay_level})."
                    ),
                )
                db.add(ledger_carrier)

        await db.flush()
        return settlement
