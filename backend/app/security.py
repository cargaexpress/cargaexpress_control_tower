import hmac

from fastapi import Header, HTTPException, status

from app.config import settings


# Fail closed when no admin key is configured; compare secrets in constant time.
# A single shared token is adequate here; JWT is unnecessary without user identities.
async def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Protect administration endpoints requiring the ADMIN_API_KEY secret.

    - Without ADMIN_API_KEY configured: 503 (secure by default, never left unprotected).
    - Missing or incorrect X-Admin-Token header: 401.
    """
    expected = settings.admin_api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Endpoints de administración deshabilitados: falta configurar ADMIN_API_KEY.",
        )
    if x_admin_token is None or not hmac.compare_digest(
        x_admin_token.encode(), expected.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de administración inválido o ausente (header X-Admin-Token).",
        )
