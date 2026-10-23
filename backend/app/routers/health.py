import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service health and connectivity probe",
    description="Check service availability and report database connection status. Always returns HTTP 200 with connectivity detail (up/down).",
    responses={
        200: {
            "description": "Service health status and database connectivity.",
            "model": HealthResponse,
        },
    },
)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Check service availability and report database connection status."""
    db_status = "up"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "down"
        logger.exception("Database health check failed")

    return HealthResponse(status="ok", database=db_status)


@router.get(
    "/ready",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
    description="Returns 200 only when the database is reachable.",
    responses={
        200: {"description": "The service is ready to serve traffic.", "model": HealthResponse},
        503: {"description": "The database is not reachable.", "model": HealthResponse},
    },
)
async def readiness_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Return readiness state for the API and database."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Database readiness check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not reachable."
        ) from exc
    return HealthResponse(status="ok", database="up")
