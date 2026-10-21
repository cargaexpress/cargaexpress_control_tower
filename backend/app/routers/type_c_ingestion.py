import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.type_c_connector import TypeCConnectorService

logger = logging.getLogger("cargaexpress.type_c_router")

router = APIRouter(prefix="/api/v1/sync/type-c", tags=["connectors: type c"])


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
