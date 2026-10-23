import hmac

from fastapi import Depends, Header, HTTPException, status

from app.config import settings


def _validate_header_secret(
    value: str | None, expected: str, header_name: str, secret_name: str
) -> None:
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


async def require_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """Protect administration endpoints requiring the ADMIN_API_KEY secret."""
    _validate_header_secret(x_admin_token, settings.admin_api_key, "X-Admin-Token", "ADMIN_API_KEY")


def _configured_api_keys() -> tuple[str, ...]:
    return tuple(key for key in (settings.api_key, *settings.brand_api_keys) if key)


async def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Protect shared API routes requiring a configured API key."""
    configured_api_keys = _configured_api_keys()
    if not configured_api_keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_KEY is not configured.",
        )
    if x_api_key is None or not any(
        hmac.compare_digest(x_api_key.encode(), key.encode()) for key in configured_api_keys
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing secret token (X-API-Key header).",
        )


async def get_current_brand(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    _: None = Depends(require_api_key),
) -> int:
    """Resolve the authenticated tenant from its API key, never from a client-supplied brand ID."""
    for api_key, brand_id in settings.brand_api_keys.items():
        if x_api_key is not None and hmac.compare_digest(x_api_key.encode(), api_key.encode()):
            return brand_id
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API key is not associated with a brand.",
    )
