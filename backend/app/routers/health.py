from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service health and connectivity probe",
    description="Check service availability and report database connection status. Always returns HTTP 200 with connectivity detail (up/down).",
    responses={
        200: {"description": "Service health status and database connectivity.", "model": HealthResponse},
    },
)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Check service availability and report database connection status.

    Does not return 500 if database query fails: always returns 200 with connectivity detail,
    allowing orchestrators (Docker / ALB) to confirm the process is alive.
    """
    db_status = "up"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "down"

    return HealthResponse(status="ok", database=db_status)
