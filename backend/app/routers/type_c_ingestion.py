import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.type_c_connector import TypeCConnectorService

logger = logging.getLogger("cargaexpress.type_c_router")

router = APIRouter(prefix="/api/v1/sync/type-c", tags=["connectors: type c"])


@router.post("")
@router.post("/sync")
async def trigger_type_c_sync(
    carrier_name: str | None = Query(
        default=None,
        description="Optional carrier name. If omitted, synchronizes all Type C sources.",
    ),
    source: str = Query(
        default="all",
        description="Source to pull from: 'endpoints', 'minio', or 'all'",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger pull synchronization for Type C batch files from carrier endpoints and MinIO S3.

    Downloads newly generated CSV/Excel files from Carrier servers or MinIO S3 bucket,
    deduplicates against previously ingested files, and normalizes events to canonical states.
    """
    service = TypeCConnectorService()
    if source == "endpoints":
        if carrier_name:
            from app.config import settings

            base_url = settings.type_c_carriers_urls.get(carrier_name, "http://localhost:8005")
            results = await service.sync_from_carrier_endpoints(db, {carrier_name: base_url})
        else:
            results = await service.sync_from_carrier_endpoints(db)
    elif source == "minio":
        results = await service.sync_from_minio_s3(db)
    else:
        results = await service.sync_all_sources(db)

    return {
        "status": "completed",
        "total_files_evaluated": len(results),
        "results": [
            {
                "filename": r.filename,
                "carrier_name": r.carrier_name,
                "status": r.status,
                "already_processed": r.already_processed,
                "total_rows_read": r.total_rows_read,
                "valid_rows_processed": r.valid_rows_processed,
                "anomalies_detected": r.anomalies_detected,
                "errors": r.errors,
                "message": r.message,
            }
            for r in results
        ],
    }


@router.post("/upload")
async def upload_type_c_file(
    file: UploadFile = File(...),
    carrier_name: str = Form(
        ...,
        description="Name of the Type C carrier (e.g. TransExpress Logistics, Rapido Andino, Logistica 360).",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upload and ingest a Type C batch file (CSV or Excel).

    Cleans known defects (repeated headers, total/summary rows),
    prevents duplicate ingestion via SHA-256 and filename tracking,
    and normalizes all valid tracking events using NormalizationService.
    """
    content = await file.read()
    service = TypeCConnectorService()
    result = await service.process_file_content(
        db=db,
        filename=file.filename or "unknown_file",
        content=content,
        carrier_name=carrier_name,
    )

    return {
        "status": result.status,
        "filename": result.filename,
        "carrier_name": result.carrier_name,
        "already_processed": result.already_processed,
        "total_rows_read": result.total_rows_read,
        "valid_rows_processed": result.valid_rows_processed,
        "total_rows_skipped": result.total_rows_skipped,
        "header_rows_skipped": result.header_rows_skipped,
        "anomalies_detected": result.anomalies_detected,
        "errors": result.errors,
        "message": result.message,
    }
