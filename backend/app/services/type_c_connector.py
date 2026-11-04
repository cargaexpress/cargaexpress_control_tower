import asyncio
import csv
import hashlib
import io
import logging
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import openpyxl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.processed_file import ProcessedFile
from app.services.normalization_service import normalize_and_apply_event

logger = logging.getLogger("cargaexpress.type_c_connector")

# Keywords identifying total or summary rows (Defect 5.3)
SUMMARY_KEYWORDS = {
    "TOTAL",
    "SUBTOTAL",
    "TOTAL REGISTROS",
    "TOTAL FILAS",
    "RESUMEN",
    "FIN DE LOTE",
    "CANTIDAD TOTAL",
    "FIN DE ARCHIVO",
}

# Possible column names for heterogeneous header mapping
TRACKING_COL_CANDIDATES = {
    "tracking_number",
    "tracking",
    "guia",
    "numero_guia",
    "waybill_no",
    "tracking_code",
    "awb",
}

STATUS_COL_CANDIDATES = {
    "status",
    "status_code",
    "estado",
    "estado_operativo",
    "code",
    "raw_status",
}

TIMESTAMP_COL_CANDIDATES = {
    "timestamp",
    "event_time",
    "fecha",
    "fecha_hora_evento",
    "event_date",
    "occurred_at",
    "date",
}


@dataclass(slots=True)
class FileProcessingResult:
    """Result summary of ingesting a single Type C file."""

    filename: str
    carrier_name: str
    file_hash: str
    already_processed: bool = False
    total_rows_read: int = 0
    valid_rows_processed: int = 0
    total_rows_skipped: int = 0
    header_rows_skipped: int = 0
    anomalies_detected: int = 0
    errors: int = 0
    status: str = "completed"
    message: str = ""
    details: list[dict[str, Any]] = field(default_factory=list)


def calculate_file_hash(content: bytes) -> str:
    """Compute SHA-256 hash of file content for deduplication."""
    return hashlib.sha256(content).hexdigest()


def parse_mixed_datetime(raw_date: Any) -> datetime | None:
    """Handle mixed DD/MM and MM/DD date formats and ISO strings (Defect 5.3)."""
    if raw_date is None:
        return None
    if isinstance(raw_date, datetime):
        if raw_date.tzinfo is None:
            return raw_date.replace(tzinfo=UTC)
        return raw_date.astimezone(UTC)

    date_str = str(raw_date).strip()
    if not date_str:
        return None

    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            continue

    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def is_summary_or_total_row(row_values: list[str]) -> bool:
    """Detect if a row is a summary or total row (Defect 5.3)."""
    clean_cells = [str(cell).strip().upper() for cell in row_values if cell is not None]
    if not clean_cells:
        return True

    joined_text = " ".join(clean_cells)
    return any(keyword in joined_text for keyword in SUMMARY_KEYWORDS)


def is_repeated_header(row_values: list[str], detected_headers: dict[str, int]) -> bool:
    """Detect if a row repeats header names (Defect 5.3)."""
    clean_cells = {str(cell).strip().lower() for cell in row_values if cell is not None}
    header_names = set(detected_headers.keys())
    # If the row has overlap with tracked column names, it's a repeated header
    return len(clean_cells.intersection(header_names)) >= 2


def match_column_indices(header_row: list[str]) -> dict[str, int]:
    """Map required logical fields (tracking, status, timestamp) to their column indices."""
    indices: dict[str, int] = {}
    for idx, col in enumerate(header_row):
        col_name = str(col).strip().lower() if col else ""
        if col_name in TRACKING_COL_CANDIDATES and "tracking" not in indices:
            indices["tracking"] = idx
            indices[col_name] = idx
        elif col_name in STATUS_COL_CANDIDATES and "status" not in indices:
            indices["status"] = idx
            indices[col_name] = idx
        elif col_name in TIMESTAMP_COL_CANDIDATES and "timestamp" not in indices:
            indices["timestamp"] = idx
            indices[col_name] = idx

    return indices


def extract_rows_from_csv(content: bytes) -> list[list[str]]:
    """Decode and extract rows from raw CSV bytes with dynamic delimiter sniffing."""
    text = content.decode("utf-8-sig", errors="replace")
    sample = text[:2048]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except Exception:
        if ";" in sample and "," not in sample:
            delimiter = ";"

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [row for row in reader if any(cell.strip() for cell in row)]


def extract_rows_from_excel(content: bytes) -> list[list[str]]:
    """Extract rows from raw Excel (.xlsx) bytes."""
    wb = openpyxl.load_workbook(filename=io.BytesIO(content), data_only=True)
    sheet = wb.active
    rows: list[list[str]] = []
    for row in sheet.iter_rows(values_only=True):
        str_row = [str(cell).strip() if cell is not None else "" for cell in row]
        if any(str_row):
            rows.append(str_row)
    return rows


class TypeCConnectorService:
    """Processes Type C carrier files (F5 / Batch), cleaning defects and updating WMS."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        max_retries: int | None = None,
        base_delay_seconds: float | None = None,
        sleep_fn: Callable[[float], Any] | None = None,
    ) -> None:
        self._external_client = client
        self.max_retries = max_retries if max_retries is not None else settings.type_c_max_retries
        self.base_delay = (
            base_delay_seconds
            if base_delay_seconds is not None
            else settings.type_c_retry_base_delay_seconds
        )
        self._sleep = sleep_fn or asyncio.sleep

    async def _do_sleep(self, delay: float) -> None:
        res = self._sleep(delay)
        if asyncio.iscoroutine(res):
            await res

    async def is_file_already_processed(
        self, db: AsyncSession, filename: str, file_hash: str
    ) -> bool:
        """Check if file has already been ingested to enforce batch idempotency (CT-08)."""
        stmt = select(ProcessedFile).where(
            (ProcessedFile.filename == filename) | (ProcessedFile.file_hash == file_hash)
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        return existing is not None

    async def process_file_content(
        self,
        db: AsyncSession,
        filename: str,
        content: bytes,
        carrier_name: str,
        archive_path: Path | None = None,
    ) -> FileProcessingResult:
        """Parse, clean known defects, deduplicate, and normalize a Type C batch file."""
        file_hash = calculate_file_hash(content)
        result = FileProcessingResult(
            filename=filename,
            carrier_name=carrier_name,
            file_hash=file_hash,
        )

        # 1. Subtask 3: Check and record already processed files (Idempotency CT-08)
        if await self.is_file_already_processed(db, filename, file_hash):
            logger.info("File %s (hash=%s) was already processed. Skipping.", filename, file_hash)
            result.already_processed = True
            result.status = "skipped"
            result.message = f"File '{filename}' has already been processed."
            return result

        # 2. Subtask 1: Parse CSV / Excel
        lower_fn = filename.lower()
        if lower_fn.endswith(".xlsx") or lower_fn.endswith(".xls"):
            raw_rows = extract_rows_from_excel(content)
        elif lower_fn.endswith(".csv"):
            raw_rows = extract_rows_from_csv(content)
        else:
            result.status = "failed"
            result.message = f"Unsupported file extension in '{filename}'"
            return result

        if not raw_rows:
            result.status = "completed"
            result.message = "File is empty."
            return result

        # 3. Detect initial header
        header_row = raw_rows[0]
        col_indices = match_column_indices(header_row)

        if "tracking" not in col_indices or "status" not in col_indices:
            result.status = "failed"
            result.message = f"Missing required columns in '{filename}'. Found: {header_row}"
            return result

        tracking_idx = col_indices["tracking"]
        status_idx = col_indices["status"]
        timestamp_idx = col_indices.get("timestamp")

        # 4. Process and clean rows (filtering totals and repeated headers)
        for row_idx, row in enumerate(raw_rows[1:], start=2):
            result.total_rows_read += 1

            # Defect 5.3: Skip total and summary footer rows
            if is_summary_or_total_row(row):
                result.total_rows_skipped += 1
                logger.debug("Skipped total/summary row %d: %s", row_idx, row)
                continue

            # Defect 5.3: Skip repeated header rows mid-batch
            if is_repeated_header(row, col_indices):
                result.header_rows_skipped += 1
                result.total_rows_skipped += 1
                logger.debug("Skipped repeated header row %d: %s", row_idx, row)
                continue

            if len(row) <= max(tracking_idx, status_idx):
                result.errors += 1
                continue

            tracking_number = row[tracking_idx].strip()
            raw_status = row[status_idx].strip()
            raw_timestamp = (
                row[timestamp_idx]
                if timestamp_idx is not None and len(row) > timestamp_idx
                else None
            )
            occurred_at = parse_mixed_datetime(raw_timestamp)

            if not tracking_number or not raw_status:
                result.errors += 1
                continue

            # 5. Subtask 2: Reuse normalization service (RN-01, RN-02, RN-07)
            try:
                norm_res = await normalize_and_apply_event(
                    db=db,
                    carrier_identifier=carrier_name,
                    tracking_number=tracking_number,
                    raw_status=raw_status,
                    occurred_at=occurred_at,
                )
                if norm_res.is_anomaly:
                    result.anomalies_detected += 1
                result.valid_rows_processed += 1
            except Exception as exc:
                logger.warning(
                    "Error normalizing row %d (tracking=%s): %s", row_idx, tracking_number, exc
                )
                result.errors += 1

        # 6. Record processed file in database to ensure deduplication (Subtask 3)
        processed_file_record = ProcessedFile(
            filename=filename,
            file_hash=file_hash,
            carrier_name=carrier_name,
            total_records=result.total_rows_read,
            valid_records=result.valid_rows_processed,
            anomalies_count=result.anomalies_detected,
        )
        db.add(processed_file_record)
        await db.commit()

        result.status = "completed"
        result.message = (
            f"Successfully processed {result.valid_rows_processed} events "
            f"from '{filename}' ({result.anomalies_detected} anomalies, "
            f"{result.total_rows_skipped} summary/header rows skipped)."
        )

        return result

    async def fetch_carrier_file(
        self,
        client: httpx.AsyncClient,
        carrier_name: str,
        base_url: str,
    ) -> tuple[str, bytes] | None:
        """Download latest batch file directly from carrier server endpoint (/download)."""
        url = f"{base_url.rstrip('/')}/download"
        delay = self.base_delay

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = await client.get(url, timeout=15.0)
                if resp.status_code == 200:
                    cd = resp.headers.get("content-disposition", "")
                    filename = ""
                    if "filename=" in cd:
                        filename = cd.split("filename=")[-1].strip("\"'; ")
                    if not filename:
                        fmt = (
                            "xlsx"
                            if "2" in carrier_name or "andino" in carrier_name.lower()
                            else "csv"
                        )
                        filename = f"{carrier_name.replace(' ', '_').lower()}_latest.{fmt}"
                    return filename, resp.content
                elif resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        "Attempt %d: Carrier %s returned HTTP %d",
                        attempt,
                        carrier_name,
                        resp.status_code,
                    )
                    await self._do_sleep(delay)
                    delay *= 2
                else:
                    logger.error(
                        "Carrier %s returned non-retryable HTTP %d",
                        carrier_name,
                        resp.status_code,
                    )
                    return None
            except Exception as exc:
                logger.warning(
                    "Attempt %d: Connection error querying carrier %s: %s",
                    attempt,
                    carrier_name,
                    exc,
                )
                if attempt == self.max_retries:
                    logger.error("Exhausted retries fetching file from %s: %s", carrier_name, exc)
                    return None
                await self._do_sleep(delay)
                delay *= 2

        return None

    async def _sync_endpoints_impl(
        self, client: httpx.AsyncClient, db: AsyncSession, urls: dict[str, str]
    ) -> list[FileProcessingResult]:
        results: list[FileProcessingResult] = []
        for carrier_name, base_url in urls.items():
            logger.info("Polling batch file for %s from %s", carrier_name, base_url)
            file_tuple = await self.fetch_carrier_file(client, carrier_name, base_url)
            if file_tuple is None:
                results.append(
                    FileProcessingResult(
                        filename=f"{carrier_name}_latest",
                        carrier_name=carrier_name,
                        file_hash="",
                        status="failed",
                        message=f"Failed to fetch batch file from {base_url}",
                    )
                )
                continue

            filename, content = file_tuple
            res = await self.process_file_content(
                db=db,
                filename=filename,
                content=content,
                carrier_name=carrier_name,
            )
            results.append(res)
        return results

    async def sync_from_carrier_endpoints(
        self,
        db: AsyncSession,
        carrier_urls: dict[str, str] | None = None,
    ) -> list[FileProcessingResult]:
        """Poll and ingest latest batch files across configured Type C carrier servers."""
        urls = carrier_urls or settings.type_c_carriers_urls
        if self._external_client:
            return await self._sync_endpoints_impl(self._external_client, db, urls)
        async with httpx.AsyncClient() as client:
            return await self._sync_endpoints_impl(client, db, urls)

    async def _sync_minio_impl(
        self, client: httpx.AsyncClient, db: AsyncSession, s3_endpoint: str, s3_bucket: str
    ) -> list[FileProcessingResult]:
        results: list[FileProcessingResult] = []
        list_url = f"{s3_endpoint}/{s3_bucket}"
        try:
            resp = await client.get(list_url, timeout=10.0)
            if resp.status_code != 200:
                logger.warning(
                    "MinIO S3 list bucket returned HTTP %d for %s",
                    resp.status_code,
                    list_url,
                )
                return results

            root = ET.fromstring(resp.content)
            keys: list[str] = []
            for elem in root.iter():
                if elem.tag.endswith("Key") and elem.text:
                    keys.append(elem.text.strip())

            for key in keys:
                filename = Path(key).name
                carrier_name = "TransExpress Logistics"
                key_upper = key.upper()
                if "CARRIER_2" in key_upper or "RAPIDO" in key_upper or "ANDINO" in key_upper:
                    carrier_name = "Rapido Andino"
                elif "CARRIER_3" in key_upper or "360" in key_upper:
                    carrier_name = "Logistica 360"

                stmt = select(ProcessedFile).where(ProcessedFile.filename == filename)
                if (await db.execute(stmt)).scalar_one_or_none() is not None:
                    continue

                get_url = f"{s3_endpoint}/{s3_bucket}/{key}"
                obj_resp = await client.get(get_url, timeout=20.0)
                if obj_resp.status_code == 200:
                    res = await self.process_file_content(
                        db=db,
                        filename=filename,
                        content=obj_resp.content,
                        carrier_name=carrier_name,
                    )
                    results.append(res)
        except Exception as exc:
            logger.warning("Error querying MinIO S3 bucket %s: %s", s3_bucket, exc)

        return results

    async def sync_from_minio_s3(
        self,
        db: AsyncSession,
        endpoint: str | None = None,
        bucket: str | None = None,
    ) -> list[FileProcessingResult]:
        """Ingest batch files from MinIO / S3 Object Storage bucket."""
        s3_endpoint = (endpoint or settings.minio_endpoint).rstrip("/")
        s3_bucket = bucket or settings.minio_bucket
        if self._external_client:
            return await self._sync_minio_impl(self._external_client, db, s3_endpoint, s3_bucket)
        async with httpx.AsyncClient() as client:
            return await self._sync_minio_impl(client, db, s3_endpoint, s3_bucket)

    async def sync_all_sources(
        self,
        db: AsyncSession,
    ) -> list[FileProcessingResult]:
        """Synchronize files from both carrier direct endpoints and MinIO S3 bucket."""
        endpoint_results = await self.sync_from_carrier_endpoints(db)
        minio_results = await self.sync_from_minio_s3(db)
        return endpoint_results + minio_results
