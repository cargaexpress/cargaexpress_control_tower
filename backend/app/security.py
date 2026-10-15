import hmac

from fastapi import Header, HTTPException, status

from app.config import settings


def _validate_header_secret(value: str | None, expected: str, header_name: str, secret_name: str) -> None:
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{secret_name} is not configured.",
        )
    if value is None or not hmac.compare_digest(value.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or missing secret token ({header_name} header).",
        )


async def require_admin(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    """Protect administration endpoints requiring the ADMIN_API_KEY secret."""
    _validate_header_secret(x_admin_token, settings.admin_api_key, "X-Admin-Token", "ADMIN_API_KEY")


async def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Protect shared API routes requiring the configured service API key."""
    _validate_header_secret(x_api_key, settings.api_key, "X-API-Key", "API_KEY")


async def get_tenant_brand_id(x_brand_id: int | None = Header(default=None, alias="X-Brand-Id")) -> int:
    """Require the tenant brand id for brand-scoped endpoints."""
    if x_brand_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="X-Brand-Id header is required.",
        )
    return x_brand_id
