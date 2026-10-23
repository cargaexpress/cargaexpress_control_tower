"""Automated batch file ingestion pipeline for Type C carriers (Source F5).

Airflow User Stories:
- HU-28 (RIWI-139): Type-C file ingestion DAG
- HU-26 (RIWI-131): Set up Airflow in Docker
- HU-29 (RIWI-143): CeleryExecutor distributed task orchestration

Architecture:
Uses Airflow TaskFlow API (@dag and @task decorators) for clean parameter passing
and decoupled execution. Reuses Sprint 2 Type C Connector (HU-22 / TypeCConnectorService)
via ControlTowerClient to sanitize repeated headers, drop summary rows, deduplicate SHA-256
hashes, and apply canonical state transitions.
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from airflow.decorators import dag, task
from utils.control_tower_client import ControlTowerClient

logger = logging.getLogger("airflow.task")

DATA_BASE_DIR = os.getenv("AIRFLOW_DATA_DIR", "/opt/airflow/data")
INCOMING_DIR = os.path.join(DATA_BASE_DIR, "type_C_simulation_data")
PROCESSED_DIR = os.path.join(INCOMING_DIR, "processed")

# Carrier name resolution from filename patterns
CARRIER_HINTS: dict[str, str] = {
    "CARRIER_1": "TransExpress Logistics",
    "TRANSEXPRESS": "TransExpress Logistics",
    "CARRIER_2": "Rapido Andino",
    "RAPIDO": "Rapido Andino",
    "ANDINO": "Rapido Andino",
    "CARRIER_3": "Logistica 360",
    "360": "Logistica 360",
}
DEFAULT_CARRIER_NAME = "TransExpress Logistics"


def resolve_carrier_name(filename: str) -> str:
    """Infer Type C carrier name from batch filename."""
    upper_name = filename.upper()
    for hint, carrier in CARRIER_HINTS.items():
        if hint in upper_name:
            return carrier
    return DEFAULT_CARRIER_NAME


@dag(
    dag_id="type_c_file_ingestion",
    schedule="0 */4 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "airflow",
        "depends_on_past": False,
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(minutes=30),
    },
    tags=["ingestion", "type-c", "batch", "wms"],
    doc_md=__doc__,
)
def type_c_file_ingestion_pipeline() -> None:
    """Orchestrates periodic scanning, connector upload, and file archival."""

    @task
    def scan_incoming_files() -> list[str]:
        """Detect unprocessed CSV or Excel files in the incoming staging volume."""
        if not os.path.exists(INCOMING_DIR):
            os.makedirs(INCOMING_DIR, exist_ok=True)
            logger.info("Created missing incoming staging directory: %s", INCOMING_DIR)

        search_patterns = [
            os.path.join(INCOMING_DIR, "*.csv"),
            os.path.join(INCOMING_DIR, "*.xlsx"),
            os.path.join(INCOMING_DIR, "*.xls"),
        ]

        found: list[str] = []
        for pattern in search_patterns:
            found.extend(glob.glob(pattern))

        # Filter out Excel temp files and subdirectories
        eligible = [
            f
            for f in found
            if not os.path.basename(f).startswith("~$")
            and os.path.isfile(f)
            and "processed" not in Path(f).parts
        ]

        logger.info(
            "Found %d candidate batch file(s) in %s: %s",
            len(eligible),
            INCOMING_DIR,
            [os.path.basename(f) for f in eligible],
        )
        return eligible

    @task
    def ingest_batch_files(file_paths: list[str]) -> list[dict[str, Any]]:
        """Upload candidate batch files to Control Tower Type C connector."""
        if not file_paths:
            logger.info("No incoming batch files to process. Skipping.")
            return []

        client = ControlTowerClient()
        results: list[dict[str, Any]] = []

        for file_path in file_paths:
            filename = os.path.basename(file_path)
            carrier_name = resolve_carrier_name(filename)
            logger.info(
                "Processing batch file '%s' (resolved carrier: '%s')",
                filename,
                carrier_name,
            )

            try:
                res = client.upload_type_c_file(
                    file_path=file_path,
                    carrier_name=carrier_name,
                )
                logger.info(
                    "Upload success for '%s': status=%s, valid_rows=%s, skipped=%s, anomalies=%s",
                    filename,
                    res.get("status"),
                    res.get("valid_rows_processed"),
                    res.get("total_rows_skipped"),
                    res.get("anomalies_detected"),
                )
                results.append(
                    {
                        "file_path": file_path,
                        "status": res.get("status", "completed"),
                        "carrier_name": carrier_name,
                        "already_processed": res.get("already_processed", False),
                        "details": res,
                    }
                )
            except Exception as exc:
                logger.error("Failed to process batch file '%s': %s", filename, exc, exc_info=True)
                results.append(
                    {
                        "file_path": file_path,
                        "status": "failed",
                        "carrier_name": carrier_name,
                        "error": str(exc),
                    }
                )

        return results

    @task
    def archive_processed_files(results: list[dict[str, Any]]) -> int:
        """Move successfully processed or idempotent files into the processed archive folder."""
        if not results:
            logger.info("No files to archive.")
            return 0

        os.makedirs(PROCESSED_DIR, exist_ok=True)
        archived_count = 0

        for item in results:
            file_path = item.get("file_path")
            status = item.get("status")
            if not file_path or not os.path.exists(file_path):
                continue

            if status in ("completed", "skipped"):
                filename = os.path.basename(file_path)
                timestamp_prefix = datetime.now().strftime("%Y%m%d_%H%M%S")
                target_name = f"{timestamp_prefix}_{filename}"
                target_path = os.path.join(PROCESSED_DIR, target_name)

                shutil.move(file_path, target_path)
                logger.info("Archived '%s' -> '%s'", file_path, target_path)
                archived_count += 1
            else:
                logger.warning(
                    "Retaining unarchived file '%s' due to status: %s",
                    file_path,
                    status,
                )

        logger.info("Total files archived in this run: %d", archived_count)
        return archived_count

    incoming_files = scan_incoming_files()
    processed_results = ingest_batch_files(incoming_files)
    archive_processed_files(processed_results)


type_c_file_ingestion_pipeline()
