"""Generador reproducible de archivos de eventos en lote para transportadoras Tipo C (Fuente F5)."""

import csv
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import random
from typing import Any, Dict, List, Optional

import openpyxl

from simulators.type_c.catalogs import CarrierConfig, get_carrier_config
from simulators.type_c.corruption import apply_all_corruptions


class TypeCSimulator:
    """Simulador de eventos en lote para transportadoras Tipo C con inyección de defectos."""

    def __init__(
        self,
        carrier: int | str | CarrierConfig,
        seed: int = 42,
        error_rate: float = 0.1,
    ) -> None:
        if isinstance(carrier, CarrierConfig):
            self.config = carrier
        else:
            self.config = get_carrier_config(carrier)

        self.seed = seed
        self.error_rate = max(0.0, min(1.0, error_rate))
        self.rng = random.Random(seed)

    def generate_events(
        self,
        num_rows: int = 100,
        universe_guides: Optional[List[str]] = None,
        base_datetime: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Genera la lista estructurada de eventos, aplicando inyección de defectos si corresponde."""
        if base_datetime is None:
            # Fecha base fija y determinista (UTC)
            base_datetime = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)

        # Determinar universo de guías legítimas
        events_per_guide = max(1, len(self.config.status_flow))
        num_guides = max(1, num_rows // events_per_guide + 1)

        if universe_guides:
            guides = universe_guides[:num_guides]
            while len(guides) < num_guides:
                guides.append(f"WMS-TRK-{self.config.carrier_id}-{len(guides) + 1:05d}")
        else:
            guides = [f"WMS-TRK-{self.config.carrier_id}-{i + 1:05d}" for i in range(num_guides)]

        raw_events: List[Dict[str, Any]] = []

        hubs_c1 = ["BOGOTA_HUB", "MEDELLIN_HUB", "CALI_HUB", "BARRANQUILLA_HUB"]
        sucursales_c2 = ["Principal Bogotá", "Centro Medellín", "Occidente Cali", "Caribe Barranquilla"]
        centers_c3 = ["DC-01", "DC-02", "DC-03", "DC-04"]

        for guide_idx, guide in enumerate(guides):
            guide_start_time = base_datetime.timestamp() + (guide_idx * 1800)  # +30 min por cada guía

            for step_idx, raw_status in enumerate(self.config.status_flow):
                if len(raw_events) >= num_rows:
                    break

                event_epoch = guide_start_time + (step_idx * 7200)  # +2 horas por estado
                event_dt = datetime.fromtimestamp(event_epoch, tz=timezone.utc)
                formatted_dt = event_dt.strftime("%Y-%m-%d %H:%M:%S")

                if self.config.carrier_id == 1:
                    row = {
                        "waybill_no": guide,
                        "status_code": raw_status,
                        "status_description": f"Shipment status is {raw_status}",
                        "event_time": formatted_dt,
                        "hub_city": hubs_c1[(guide_idx + step_idx) % len(hubs_c1)],
                    }
                elif self.config.carrier_id == 2:
                    obs = "Operación normal" if step_idx < len(self.config.status_flow) - 1 else "Completado"
                    row = {
                        "numero_guia": guide,
                        "estado_operativo": raw_status,
                        "fecha_hora_evento": formatted_dt,
                        "sucursal": sucursales_c2[(guide_idx + step_idx) % len(sucursales_c2)],
                        "observaciones": obs,
                    }
                elif self.config.carrier_id == 3:
                    row = {
                        "tracking_code": guide,
                        "code": raw_status,
                        "event_date": formatted_dt,
                        "center_id": centers_c3[(guide_idx + step_idx) % len(centers_c3)],
                    }
                else:
                    row = {
                        self.config.tracking_col: guide,
                        self.config.status_col: raw_status,
                        self.config.timestamp_col: formatted_dt,
                    }

                raw_events.append(row)

            if len(raw_events) >= num_rows:
                break

        # Inyección orquestada de defectos si error_rate > 0
        if self.error_rate > 0:
            final_events = apply_all_corruptions(
                rows=raw_events,
                columns=self.config.columns,
                tracking_col=self.config.tracking_col,
                status_col=self.config.status_col,
                timestamp_col=self.config.timestamp_col,
                rng=self.rng,
                error_rate=self.error_rate,
            )
        else:
            final_events = raw_events

        return final_events

    def write_csv(self, events: List[Dict[str, Any]], output_path: Path) -> Path:
        """Escribe los eventos en archivo CSV determinista."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=self.config.columns,
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            for row in events:
                writer.writerow(row)

        return output_path

    def write_xlsx(self, events: List[Dict[str, Any]], output_path: Path) -> Path:
        """Escribe los eventos en un archivo Excel (.xlsx) determinista."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = self.config.code

        # Escribir encabezado
        ws.append(self.config.columns)

        # Escribir filas
        for row in events:
            row_vals = [row.get(col, "") for col in self.config.columns]
            ws.append(row_vals)

        wb.save(output_path)
        return output_path

    def generate_file(
        self,
        output_dir: Path | str,
        num_rows: int = 100,
        file_format: Optional[str] = None,
        filename_prefix: Optional[str] = None,
        universe_guides: Optional[List[str]] = None,
    ) -> Path:
        """Genera el dataset y lo escribe en el formato especificado (csv o xlsx)."""
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        fmt = (file_format or self.config.default_format).lower().strip().replace(".", "")
        if fmt not in {"csv", "xlsx"}:
            raise ValueError(f"Formato no soportado: '{fmt}'. Solo 'csv' o 'xlsx'.")

        prefix = filename_prefix or f"batch_{self.config.code.lower()}"
        filename = f"{prefix}_seed{self.seed}_err{int(self.error_rate * 100)}.{fmt}"
        target_path = target_dir / filename

        events = self.generate_events(num_rows=num_rows, universe_guides=universe_guides)

        if fmt == "csv":
            self.write_csv(events, target_path)
        else:
            self.write_xlsx(events, target_path)

        return target_path


def compute_file_sha256(file_path: Path) -> str:
    """Calcula el hash SHA-256 de un archivo para validar reproducibilidad exacta."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()
