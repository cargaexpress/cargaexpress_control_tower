"""Script y servicio de Seed idempotente para el WMS y transportadoras simuladas.

Garantiza la inicialización o sincronización de:
1. ShipmentTypes (STANDARD, EXPRESS, SAME_DAY).
2. Centros de Distribución (DCs).
3. Marcas comerciales (Brands).
4. Transportadoras Tipo C y sus mapeos canónicos en state_mapping.
5. Pedidos de prueba (Orders), líneas, destinatarios y guías de despacho (ShippingLabels).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import os
import random
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from simulators.type_c.catalogs import CARRIERS_REGISTRY


@dataclass
class SeedConfig:
    seed: int = 42
    orders_count: int = 20
    carriers_to_seed: List[int] = None

    def __post_init__(self):
        if self.carriers_to_seed is None:
            self.carriers_to_seed = [1, 2, 3]


class WMSSeeder:
    """Ejecutor idempotente de seeding sobre PostgreSQL / WMS."""

    def __init__(self, session: AsyncSession, config: Optional[SeedConfig] = None) -> None:
        self.session = session
        self.config = config or SeedConfig()
        self.rng = random.Random(self.config.seed)

    async def seed_shipment_types(self) -> Dict[str, str]:
        """Siembra los tipos de envío estándar si no existen."""
        from app.models.shipment_type import ShipmentType

        types = [
            ("STANDARD", "Envío terrestre estándar (3 a 5 días)"),
            ("EXPRESS", "Envío expreso prioritario (24 a 48 horas)"),
            ("SAME_DAY", "Entrega el mismo día en ciudad capital"),
        ]
        created = {}
        for code, desc in types:
            stmt = select(ShipmentType).where(ShipmentType.shipment_type_code == code)
            result = await self.session.execute(stmt)
            obj = result.scalar_one_or_none()
            if not obj:
                obj = ShipmentType(shipment_type_code=code, description=desc)
                self.session.add(obj)
            created[code] = desc
        await self.session.flush()
        return created

    async def seed_distribution_centers(self) -> Dict[str, int]:
        """Siembra centros de distribución si no existen."""
        from app.models.distribution_center import DistributionCenter

        dcs = [
            ("DC-BOG", "Centro de Distribución Bogotá Hub", "Bogotá", "CO"),
            ("DC-MED", "Centro de Distribución Medellín Antioquia", "Medellín", "CO"),
            ("DC-CLO", "Centro Logístico Occidente Cali", "Cali", "CO"),
        ]
        dc_ids = {}
        for code, name, city, country in dcs:
            stmt = select(DistributionCenter).where(DistributionCenter.code == code)
            result = await self.session.execute(stmt)
            obj = result.scalar_one_or_none()
            if not obj:
                obj = DistributionCenter(
                    code=code,
                    name=name,
                    city=city,
                    country_code=country,
                )
                self.session.add(obj)
                await self.session.flush()
            dc_ids[code] = obj.dc_id
        return dc_ids

    async def seed_brands(self) -> Dict[str, int]:
        """Siembra marcas clientes si no existen."""
        from app.models.brand import Brand

        brands = [
            ("ModaExpress S.A.S.", "TIER_1"),
            ("ElectroTech Colombia", "TIER_1"),
            ("Hogar & Confort", "TIER_2"),
        ]
        brand_ids = {}
        for name, tier in brands:
            stmt = select(Brand).where(Brand.name == name)
            result = await self.session.execute(stmt)
            obj = result.scalar_one_or_none()
            if not obj:
                obj = Brand(name=name, tier=tier, is_active=True)
                self.session.add(obj)
                await self.session.flush()
            brand_ids[name] = obj.brand_id
        return brand_ids

    async def seed_carriers_and_mappings(self) -> Dict[int, int]:
        """Siembra las transportadoras Tipo C y sus traducciones a estados canónicos (HU-12 / RN-01)."""
        from app.models.carrier import Carrier
        from app.models.state_mapping import StateMapping

        carrier_db_ids: Dict[int, int] = {}

        for c_id in self.config.carriers_to_seed:
            cfg = CARRIERS_REGISTRY[c_id]
            # Buscar o crear transportadora por nombre
            stmt = select(Carrier).where(Carrier.name == cfg.name)
            result = await self.session.execute(stmt)
            carrier_obj = result.scalar_one_or_none()

            if not carrier_obj:
                carrier_obj = Carrier(
                    name=cfg.name,
                    integration_type="batch_file",
                    status="active",
                )
                self.session.add(carrier_obj)
                await self.session.flush()

            carrier_db_ids[c_id] = carrier_obj.carrier_id

            # Sincronizar catálogo de mapeos canónicos de forma idempotente
            for raw_status, canonical_status in cfg.status_catalog.items():
                mapping_stmt = select(StateMapping).where(
                    StateMapping.carrier_id == carrier_obj.carrier_id,
                    StateMapping.raw_status == raw_status,
                )
                mapping_res = await self.session.execute(mapping_stmt)
                mapping_obj = mapping_res.scalar_one_or_none()

                if not mapping_obj:
                    mapping_obj = StateMapping(
                        carrier_id=carrier_obj.carrier_id,
                        raw_status=raw_status,
                        canonical_status=canonical_status,
                    )
                    self.session.add(mapping_obj)

        await self.session.flush()
        return carrier_db_ids

    async def seed_orders_and_labels(
        self,
        brand_ids: Dict[str, int],
        dc_ids: Dict[str, int],
        carrier_db_ids: Dict[int, int],
    ) -> List[str]:
        """Genera órdenes y guías de envío deterministas para pruebas e ingestión de archivos."""
        from app.models.order import Order
        from app.models.order_line import OrderLine
        from app.models.order_recipient import OrderRecipient
        from app.models.shipping_label import ShippingLabel

        generated_tracking_numbers: List[str] = []
        brand_id_list = list(brand_ids.values())
        dc_id_list = list(dc_ids.values())
        carrier_items = list(carrier_db_ids.items())  # [(1, db_id1), (2, db_id2), ...]

        for i in range(1, self.config.orders_count + 1):
            ref = f"ORD-SEED-{self.config.seed}-{i:04d}"
            # Comprobar si ya existe el pedido para mantener idempotencia estricta
            stmt = select(Order).where(Order.brand_order_ref == ref)
            res = await self.session.execute(stmt)
            order_obj = res.scalar_one_or_none()

            carrier_cfg_id, carrier_db_id = carrier_items[i % len(carrier_items)]
            tracking_num = f"WMS-TRK-{carrier_cfg_id}-{i:05d}"
            generated_tracking_numbers.append(tracking_num)

            if not order_obj:
                brand_id = brand_id_list[i % len(brand_id_list)]
                dc_id = dc_id_list[i % len(dc_id_list)]
                shipment_type = "STANDARD" if i % 2 == 0 else "EXPRESS"

                order_obj = Order(
                    brand_id=brand_id,
                    dc_id=dc_id,
                    shipment_type_code=shipment_type,
                    brand_order_ref=ref,
                    destination_country="CO",
                    destination_region="Cundinamarca",
                    freight_value=Decimal("15000.00"),
                    status="CREATED",
                )
                self.session.add(order_obj)
                await self.session.flush()

                # Líneas de pedido
                line = OrderLine(
                    order_id=order_obj.order_id,
                    line_number=1,
                    sku=f"SKU-{self.rng.randint(100, 999)}",
                    description="Artículo de prueba de seed",
                    quantity_ordered=self.rng.randint(1, 3),
                )
                self.session.add(line)

                # Destinatario
                recipient = OrderRecipient(
                    order_id=order_obj.order_id,
                    full_name=f"Cliente Prueba {i}",
                    email=f"cliente{i}@ejemplo.com",
                    phone="+573001234567",
                    address_line=f"Calle {10 + i} # {20 + i} - {30 + i}",
                    city="Bogotá",
                )
                self.session.add(recipient)

                # Guía de despacho (ShippingLabel)
                label = ShippingLabel(
                    order_id=order_obj.order_id,
                    carrier_id=carrier_db_id,
                    tracking_number=tracking_num,
                    status="CREATED",
                    weight_kg=Decimal("1.500"),
                )
                self.session.add(label)

        await self.session.commit()
        return generated_tracking_numbers

    async def execute_full_seed(self) -> Dict[str, Any]:
        """Ejecuta el pipeline completo de seed de manera idempotente."""
        st = await self.seed_shipment_types()
        dcs = await self.seed_distribution_centers()
        brands = await self.seed_brands()
        carriers = await self.seed_carriers_and_mappings()
        tracking_numbers = await self.seed_orders_and_labels(brands, dcs, carriers)

        return {
            "status": "success",
            "shipment_types_count": len(st),
            "distribution_centers_count": len(dcs),
            "brands_count": len(brands),
            "carriers_count": len(carriers),
            "tracking_numbers_count": len(tracking_numbers),
            "sample_tracking_numbers": tracking_numbers[:5],
        }


async def run_seed(database_url: Optional[str] = None, config: Optional[SeedConfig] = None) -> Dict[str, Any]:
    """Función de conveniencia para ejecutar el seed contra una base de datos PostgreSQL."""
    db_url = database_url or os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL no especificada y no presente en variables de entorno.")

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        seeder = WMSSeeder(session=session, config=config)
        result = await seeder.execute_full_seed()

    await engine.dispose()
    return result
