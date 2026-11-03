import hashlib
import hmac

from fastapi import Depends, Header, HTTPException, Request, status

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


async def verify_carrier_webhook_auth(
    carrier_slug: str,
    request: Request,
    x_carrier_token: str | None = Header(default=None, alias="X-Carrier-Token"),
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
    x_signature: str | None = Header(default=None, alias="X-Signature-SHA256"),
    x_hub_signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> None:
    """Validate incoming carrier webhook authentication and payload integrity (NFR-06).

    Supports:
    1. Direct bearer/header tokens: X-Carrier-Token or X-Webhook-Secret.
    2. HMAC-SHA256 signature verification over request body: X-Signature-SHA256 or X-Hub-Signature-256.
    """
    clean_slug = carrier_slug.strip().lower()
    carrier_token = settings.carrier_webhook_tokens.get(clean_slug)
    configured_secrets = [s for s in (carrier_token, settings.webhook_secret) if s]

    is_production = settings.app_env.strip().lower() == "production"

    if not configured_secrets:
        if is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Carrier webhook authentication secret is not configured in production.",
            )
        # In non-production, if no webhook secret is configured, allow unauthenticated request unless token provided
        if (
            x_carrier_token is None
            and x_webhook_secret is None
            and x_signature is None
            and x_hub_signature is None
        ):
            return

    # Check HMAC signature if provided
    sig_header = x_signature or x_hub_signature
    if sig_header and settings.webhook_secret:
        body = await request.body()
        expected_sig = hmac.new(
            settings.webhook_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        clean_sig = sig_header.removeprefix("sha256=").strip()
        if hmac.compare_digest(clean_sig.encode(), expected_sig.encode()):
            return

    # Check secret tokens
    token_candidate = x_carrier_token or x_webhook_secret
    if token_candidate:
        if any(
            hmac.compare_digest(token_candidate.encode(), expected.encode())
            for expected in configured_secrets
        ):
            return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized carrier webhook. Invalid or missing secret token/signature.",
    )
