from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
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
