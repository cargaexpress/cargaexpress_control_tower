import calendar
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import (
    DimBrand,
    DimCarrier,
    DimDate,
    DimDistributionCenter,
    DimGeography,
    DimShipmentStatus,
    EtlBatchRun,
    EtlRejectedRecord,
    FactCarrierSettlement,
    FactFinancialPenalty,
    FactShipmentEvent,
    FactShipmentSla,
)
from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.dispatch import Dispatch
from app.models.distribution_center import DistributionCenter
from app.models.financial import FinancialSettlement, FreightPenalty
from app.models.order import Order
from app.models.shipping_label import ShippingLabel
from app.models.sla_tracking import ShipmentSlaTracking
from app.models.tracking_anomaly import TrackingAnomaly
from app.services.sla_engine import SlaEngineService

logger = logging.getLogger("cargaexpress.analytical_etl")


class AnalyticalEtlService:
    """Core domain service for extracting operational data, performing data quality checks,
    transforming data into the Kimball dimensional star schema, and recording lineage (Work Package 2).
    """

    def __init__(self, sla_engine: SlaEngineService | None = None) -> None:
        self.sla_engine = sla_engine or SlaEngineService()

    @staticmethod
    def to_date_key(d: date | datetime | None) -> int | None:
        """Convert a date or datetime to an integer date key format (YYYYMMDD)."""
        if d is None:
            return None
        if isinstance(d, datetime):
            d = d.date()
        return d.year * 10000 + d.month * 100 + d.day

    # =========================================================================
    # 1. Dimension Synchronization & Pre-population
    # =========================================================================

    async def sync_calendar_dates(
        self,
        db: AsyncSession,
        start_year: int = 2025,
        end_year: int = 2027,
    ) -> None:
        """Populate dim_dates dimension table with calendar attributes, weekends, and official holidays."""
        start_date = date(start_year, 1, 1)
        end_date = date(end_year, 12, 31)

        # Preload existing date keys to avoid redundant lookups
        existing_res = await db.execute(select(DimDate.date_key))
        existing_keys = set(existing_res.scalars().all())

        # Preload official holidays per country and year
        co_holidays: set[date] = set()
        mx_holidays: set[date] = set()
        pe_holidays: set[date] = set()
        for yr in range(start_year, end_year + 1):
            co_holidays.update(
                await self.sla_engine.get_holidays_for_country_and_year(db, "CO", yr)
            )
            mx_holidays.update(
                await self.sla_engine.get_holidays_for_country_and_year(db, "MX", yr)
            )
            pe_holidays.update(
                await self.sla_engine.get_holidays_for_country_and_year(db, "PE", yr)
            )

        curr = start_date
        while curr <= end_date:
            d_key = self.to_date_key(curr)
            assert d_key is not None

            if d_key not in existing_keys:
                is_sun = curr.weekday() == 6
                is_sat = curr.weekday() == 5
                is_h_co = curr in co_holidays
                is_h_mx = curr in mx_holidays
                is_h_pe = curr in pe_holidays

                dim_d = DimDate(
                    date_key=d_key,
                    calendar_date=curr,
                    year=curr.year,
                    quarter=(curr.month - 1) // 3 + 1,
                    month=curr.month,
                    month_name=calendar.month_name[curr.month],
                    day_of_month=curr.day,
                    day_of_week=curr.weekday() + 1,  # 1=Monday, 7=Sunday
                    day_name=calendar.day_name[curr.weekday()],
                    is_weekend=is_sat or is_sun,
                    is_sunday=is_sun,
                    is_holiday_co=is_h_co,
                    is_holiday_mx=is_h_mx,
                    is_holiday_pe=is_h_pe,
                )
                db.add(dim_d)
                existing_keys.add(d_key)
            curr += timedelta(days=1)
        await db.flush()

    async def sync_dimensions(self, db: AsyncSession) -> dict[str, dict]:
        """Synchronize operational entities into analytical dimension tables with surrogate keys."""
        # 1. Date Dimension
        await self.sync_calendar_dates(db, 2025, 2027)

        # 2. Brands Dimension
        stmt_b = select(Brand)
        res_b = await db.execute(stmt_b)
        for b in res_b.scalars().all():
            stmt_db = select(DimBrand).where(DimBrand.brand_id == b.brand_id)
            res_db = await db.execute(stmt_db)
            db_record = res_db.scalar_one_or_none()
            if not db_record:
                db.add(
                    DimBrand(
                        brand_id=b.brand_id,
                        brand_name=b.name,
                        tier=b.tier,
                        is_active=b.is_active,
                    )
                )
            else:
                db_record.brand_name = b.name
                db_record.tier = b.tier
                db_record.is_active = b.is_active

        # 3. Carriers Dimension
        stmt_c = select(Carrier)
        res_c = await db.execute(stmt_c)
        for c in res_c.scalars().all():
            stmt_dc = select(DimCarrier).where(DimCarrier.carrier_id == c.carrier_id)
            res_dc = await db.execute(stmt_dc)
            dc_record = res_dc.scalar_one_or_none()
            if not dc_record:
                db.add(
                    DimCarrier(
                        carrier_id=c.carrier_id,
                        carrier_name=c.name,
                        integration_type=c.integration_type,
                        carrier_status=c.status,
                    )
                )
            else:
                dc_record.carrier_name = c.name
                dc_record.integration_type = c.integration_type
                dc_record.carrier_status = c.status

        # 4. Distribution Centers Dimension
        stmt_dc_op = select(DistributionCenter)
        res_dc_op = await db.execute(stmt_dc_op)
        for dc in res_dc_op.scalars().all():
            stmt_ddc = select(DimDistributionCenter).where(DimDistributionCenter.dc_id == dc.dc_id)
            res_ddc = await db.execute(stmt_ddc)
            ddc_record = res_ddc.scalar_one_or_none()
            if not ddc_record:
                db.add(
                    DimDistributionCenter(
                        dc_id=dc.dc_id,
                        dc_code=dc.code,
                        dc_name=dc.name,
                        city=dc.city,
                        country_code=dc.country_code,
                    )
                )
            else:
                ddc_record.dc_code = dc.code
                ddc_record.dc_name = dc.name
                ddc_record.city = dc.city
                ddc_record.country_code = dc.country_code

        # 5. Shipment Status Dimension (Canonical states)
        canonical_statuses = [
            ("CREATED", "ORDER", False),
            ("DISPATCHED", "TRANSIT", False),
            ("IN_TRANSIT", "TRANSIT", False),
            ("OUT_FOR_DELIVERY", "TRANSIT", False),
            ("EXCEPTION", "INCIDENT", False),
            ("DELIVERED", "TERMINAL", True),
            ("CANCELLED", "TERMINAL", True),
        ]
        for code, cat, term in canonical_statuses:
            stmt_st = select(DimShipmentStatus).where(DimShipmentStatus.status_code == code)
            res_st = await db.execute(stmt_st)
            if not res_st.scalar_one_or_none():
                db.add(
                    DimShipmentStatus(
                        status_code=code,
                        status_category=cat,
                        is_terminal=term,
                    )
                )

        # 6. Geography Dimension
        # Ensure standard default geography row always exists
        stmt_default_geo = select(DimGeography).where(
            DimGeography.country_code == "CO", DimGeography.region_name == "STANDARD"
        )
        res_dg = await db.execute(stmt_default_geo)
        if not res_dg.scalar_one_or_none():
            db.add(DimGeography(country_code="CO", region_name="STANDARD"))

        stmt_geo = select(Order.destination_country, Order.destination_region).distinct()
        res_geo = await db.execute(stmt_geo)
        for c_code, region in res_geo.all():
            country = (c_code or "CO").strip().upper()
            reg = (region or "STANDARD").strip().upper()
            stmt_dg = select(DimGeography).where(
                DimGeography.country_code == country,
                DimGeography.region_name == reg,
            )
            res_dg = await db.execute(stmt_dg)
            if not res_dg.scalar_one_or_none():
                db.add(DimGeography(country_code=country, region_name=reg))

        await db.flush()

        # Build in-memory lookup maps
        res_brands = await db.execute(select(DimBrand))
        res_carriers = await db.execute(select(DimCarrier))
        res_dcs = await db.execute(select(DimDistributionCenter))
        res_statuses = await db.execute(select(DimShipmentStatus))
        res_geos = await db.execute(select(DimGeography))

        return {
            "brands": {b.brand_id: b.brand_key for b in res_brands.scalars().all()},
            "carriers": {c.carrier_id: c.carrier_key for c in res_carriers.scalars().all()},
            "dcs": {d.dc_id: d.dc_key for d in res_dcs.scalars().all()},
            "statuses": {s.status_code: s.status_key for s in res_statuses.scalars().all()},
            "geos": {(g.country_code, g.region_name): g.geo_key for g in res_geos.scalars().all()},
        }

    # =========================================================================
    # 2. End-to-End ETL Pipeline Execution & Data Lineage
    # =========================================================================

    async def run_etl_pipeline(
        self,
        db: AsyncSession,
        pipeline_name: str = "operational_to_olap_sync",
    ) -> EtlBatchRun:
        """Execute full ETL transformation from operational OLTP schema to Kimball Star Schema.

        Tracks:
        - Lineage: batch_id assigned to every fact row.
        - Data quality: logs invalid/rejected rows to etl_rejected_records.
        - Deduplication and idempotency.
        """
        batch = EtlBatchRun(
            pipeline_name=pipeline_name,
            started_at=datetime.now(UTC),
            status="RUNNING",
        )
        db.add(batch)
        await db.flush()

        records_extracted = 0
        records_loaded = 0
        records_rejected = 0

        try:
            # 1. Sync dimensions & retrieve surrogate key lookups
            lookup = await self.sync_dimensions(db)
            brand_map = lookup["brands"]
            carrier_map = lookup["carriers"]
            dc_map = lookup["dcs"]
            status_map = lookup["statuses"]
            geo_map = lookup["geos"]

            # Fallback status key if unknown
            default_status_key = next(iter(status_map.values()), 1)
            # Fallback geo key
            default_geo_key = next(iter(geo_map.values()), 1)

            # -----------------------------------------------------------------
            # 2. Transform & Load FactShipmentSla
            # -----------------------------------------------------------------
            stmt_labels = select(ShippingLabel)
            res_labels = await db.execute(stmt_labels)
            labels = res_labels.scalars().all()

            for label in labels:
                records_extracted += 1

                # Load related order
                stmt_o = select(Order).where(Order.order_id == label.order_id)
                res_o = await db.execute(stmt_o)
                order = res_o.scalar_one_or_none()

                if not order:
                    records_rejected += 1
                    db.add(
                        EtlRejectedRecord(
                            batch_id=batch.batch_id,
                            source_table="shipping_labels",
                            source_record_id=str(label.label_id),
                            rejection_reason="Orphan shipping label without associated order",
                            raw_payload=f"label_id={label.label_id}, tracking={label.tracking_number}",
                        )
                    )
                    continue

                brand_key = brand_map.get(order.brand_id)
                carrier_key = carrier_map.get(label.carrier_id)
                dc_key = dc_map.get(order.dc_id)

                if not brand_key or not carrier_key or not dc_key:
                    records_rejected += 1
                    db.add(
                        EtlRejectedRecord(
                            batch_id=batch.batch_id,
                            source_table="shipping_labels",
                            source_record_id=str(label.label_id),
                            rejection_reason="Missing referential integrity in brand, carrier, or DC dimension",
                            raw_payload=f"label_id={label.label_id}, brand_id={order.brand_id}, carrier_id={label.carrier_id}",
                        )
                    )
                    continue

                # SLA Tracking
                stmt_sla = select(ShipmentSlaTracking).where(
                    ShipmentSlaTracking.label_id == label.label_id
                )
                res_sla = await db.execute(stmt_sla)
                sla_rec = res_sla.scalar_one_or_none()

                # Dispatch
                stmt_d = select(Dispatch.dispatched_at).where(
                    Dispatch.dispatch_id == label.dispatch_id
                )
                res_d = await db.execute(stmt_d)
                dispatched_at = res_d.scalar_one_or_none()

                c_code = (order.destination_country or "CO").strip().upper()
                reg_name = (order.destination_region or "STANDARD").strip().upper()
                geo_key = geo_map.get((c_code, reg_name), default_geo_key)
                status_key = status_map.get((label.status or "").upper(), default_status_key)

                dispatch_date_key = self.to_date_key(dispatched_at)
                deadline_date_key = self.to_date_key(sla_rec.deadline_utc if sla_rec else None)
                delivery_date_key = self.to_date_key(sla_rec.delivered_at if sla_rec else None)

                # Upsert into FactShipmentSla
                stmt_fact = select(FactShipmentSla).where(
                    FactShipmentSla.label_id == label.label_id
                )
                res_f = await db.execute(stmt_fact)
                fact_sla = res_f.scalar_one_or_none()

                freight_val = Decimal(str(order.freight_value or 0.00))

                if not fact_sla:
                    fact_sla = FactShipmentSla(
                        dispatch_date_key=dispatch_date_key,
                        deadline_date_key=deadline_date_key,
                        delivery_date_key=delivery_date_key,
                        brand_key=brand_key,
                        carrier_key=carrier_key,
                        dc_key=dc_key,
                        status_key=status_key,
                        geo_key=geo_key,
                        label_id=label.label_id,
                        order_id=order.order_id,
                        tracking_number=label.tracking_number,
                        brand_order_ref=order.brand_order_ref,
                        sla_status=sla_rec.sla_status if sla_rec else "PENDING",
                        responsible_party=sla_rec.responsible_party if sla_rec else None,
                        freight_amount=freight_val,
                        sla_target_days=sla_rec.sla_business_days if sla_rec else 3,
                        delay_business_days=0,
                        is_sla_breached=sla_rec.sla_status == "BREACHED" if sla_rec else False,
                        is_at_risk=sla_rec.is_at_risk if sla_rec else False,
                        business_hours_remaining=Decimal(str(sla_rec.business_hours_remaining))
                        if (sla_rec and sla_rec.business_hours_remaining is not None)
                        else None,
                        etl_batch_id=batch.batch_id,
                        source_system="operational_db",
                    )
                    db.add(fact_sla)
                else:
                    fact_sla.dispatch_date_key = dispatch_date_key
                    fact_sla.deadline_date_key = deadline_date_key
                    fact_sla.delivery_date_key = delivery_date_key
                    fact_sla.status_key = status_key
                    fact_sla.sla_status = sla_rec.sla_status if sla_rec else "PENDING"
                    fact_sla.is_sla_breached = (
                        sla_rec.sla_status == "BREACHED" if sla_rec else False
                    )
                    fact_sla.is_at_risk = sla_rec.is_at_risk if sla_rec else False
                    fact_sla.etl_batch_id = batch.batch_id

                records_loaded += 1

            # -----------------------------------------------------------------
            # 3. Transform & Load FactFinancialPenalty
            # -----------------------------------------------------------------
            stmt_penalties = select(FreightPenalty)
            res_p = await db.execute(stmt_penalties)
            for p in res_p.scalars().all():
                records_extracted += 1
                b_key = brand_map.get(p.brand_id)
                c_key = carrier_map.get(p.carrier_id)
                if not b_key or not c_key:
                    records_rejected += 1
                    db.add(
                        EtlRejectedRecord(
                            batch_id=batch.batch_id,
                            source_table="freight_penalties",
                            source_record_id=str(p.penalty_id),
                            rejection_reason="Missing brand or carrier key for penalty",
                            raw_payload=f"penalty_id={p.penalty_id}",
                        )
                    )
                    continue

                calc_date_key = self.to_date_key(p.calculated_at) or self.to_date_key(date.today())
                assert calc_date_key is not None

                stmt_fp = select(FactFinancialPenalty).where(
                    FactFinancialPenalty.penalty_id == p.penalty_id
                )
                res_fp = await db.execute(stmt_fp)
                fact_p = res_fp.scalar_one_or_none()

                if not fact_p:
                    fact_p = FactFinancialPenalty(
                        calculation_date_key=calc_date_key,
                        brand_key=b_key,
                        carrier_key=c_key,
                        status_key=default_status_key,
                        geo_key=default_geo_key,
                        penalty_id=p.penalty_id,
                        label_id=p.label_id,
                        tracking_number=p.tracking_number,
                        incident_reference=p.incident_reference,
                        responsible_party=p.responsible_party,
                        delay_level=p.delay_level,
                        calculation_status=p.calculation_status,
                        contract_rule_applied=p.contract_rule_applied,
                        freight_amount=p.freight_amount,
                        delay_business_days=p.delay_business_days,
                        penalty_percentage=p.penalty_percentage,
                        base_penalty_amount=p.base_penalty_amount,
                        maximum_penalty_amount=p.maximum_penalty_amount,
                        penalty_amount=p.penalty_amount,
                        is_carrier_payable=p.is_carrier_payable,
                        is_client_owed=p.is_client_owed,
                        etl_batch_id=batch.batch_id,
                        source_system="operational_db",
                    )
                    db.add(fact_p)
                else:
                    fact_p.penalty_amount = p.penalty_amount
                    fact_p.calculation_status = p.calculation_status
                    fact_p.etl_batch_id = batch.batch_id

                records_loaded += 1

            # -----------------------------------------------------------------
            # 4. Transform & Load FactShipmentEvent
            # -----------------------------------------------------------------
            stmt_events = select(TrackingAnomaly)
            res_e = await db.execute(stmt_events)
            for anom in res_e.scalars().all():
                records_extracted += 1
                c_key = carrier_map.get(anom.carrier_id)
                if not c_key:
                    records_rejected += 1
                    continue

                event_date_key = self.to_date_key(anom.created_at) or self.to_date_key(date.today())
                assert event_date_key is not None
                st_key = status_map.get(
                    (anom.current_status or "EXCEPTION").upper(), default_status_key
                )

                stmt_fe = select(FactShipmentEvent).where(
                    FactShipmentEvent.anomaly_id == anom.anomaly_id
                )
                res_fe = await db.execute(stmt_fe)
                if not res_fe.scalar_one_or_none():
                    db.add(
                        FactShipmentEvent(
                            event_date_key=event_date_key,
                            brand_key=None,
                            carrier_key=c_key,
                            status_key=st_key,
                            anomaly_id=anom.anomaly_id,
                            label_id=anom.label_id,
                            tracking_number=anom.tracking_number,
                            raw_status=anom.raw_status,
                            canonical_status=anom.current_status,
                            anomaly_type=anom.anomaly_type,
                            etl_batch_id=batch.batch_id,
                            source_system="operational_db",
                        )
                    )
                    records_loaded += 1

            # -----------------------------------------------------------------
            # 5. Transform & Load FactCarrierSettlement
            # -----------------------------------------------------------------
            stmt_settlements = select(FinancialSettlement)
            res_s = await db.execute(stmt_settlements)
            for s in res_s.scalars().all():
                records_extracted += 1
                c_key = carrier_map.get(s.carrier_id)
                if not c_key:
                    records_rejected += 1
                    continue

                p_start_key = self.to_date_key(s.period_start_date)
                p_end_key = self.to_date_key(s.period_end_date)
                assert p_start_key is not None and p_end_key is not None

                stmt_fs = select(FactCarrierSettlement).where(
                    FactCarrierSettlement.settlement_id == s.settlement_id
                )
                res_fs = await db.execute(stmt_fs)
                if not res_fs.scalar_one_or_none():
                    db.add(
                        FactCarrierSettlement(
                            period_start_date_key=p_start_key,
                            period_end_date_key=p_end_key,
                            carrier_key=c_key,
                            settlement_id=s.settlement_id,
                            period_code=s.period_code,
                            settlement_status=s.status,
                            total_penalties_count=s.total_penalties_count,
                            total_freight_amount=s.total_freight_amount,
                            total_owed_to_clients=s.total_owed_to_clients,
                            total_recoverable_from_carrier=s.total_recoverable_from_carrier,
                            net_settlement_amount=s.net_settlement_amount,
                            etl_batch_id=batch.batch_id,
                            source_system="operational_db",
                        )
                    )
                    records_loaded += 1

            # Commit batch audit run
            batch.status = "COMPLETED"
            batch.completed_at = datetime.now(UTC)
            batch.records_extracted = records_extracted
            batch.records_loaded = records_loaded
            batch.records_rejected = records_rejected
            await db.flush()
            return batch

        except Exception as exc:
            logger.exception("ETL pipeline execution failed")
            batch.status = "FAILED"
            batch.completed_at = datetime.now(UTC)
            batch.error_message = str(exc)
            batch.records_extracted = records_extracted
            batch.records_loaded = records_loaded
            batch.records_rejected = records_rejected
            await db.flush()
            raise
