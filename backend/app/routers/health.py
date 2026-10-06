from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """
    Verifica que el servicio esté arriba y reporta el estado de la conexión a la base de datos.

    No lanza error 500 si la base de datos falla: siempre responde 200 con el detalle,
    para que Docker/ALB sepan que el proceso está vivo aunque la BD tenga un problema puntual.
    """
    db_status = "up"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "down"

    return HealthResponse(status="ok", database=db_status)
