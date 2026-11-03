import hashlib
import hmac

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import create_app
from app.models.carrier import Carrier
from app.services.rabbitmq_service import QueuedWebhookMessage


@pytest.fixture
def test_app():
    return create_app()


@pytest.fixture
async def sec_client(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def setup_carrier(db_session):
    carrier = Carrier(
        carrier_id=1,
        name="SimCarrier Alpha",
        integration_type="webhook",
        status="active",
    )
    db_session.add(carrier)
    await db_session.commit()
    return carrier


@pytest.mark.asyncio
async def test_webhook_auth_success_with_carrier_token(sec_client, db_session, setup_carrier, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "secret_" + "a" * 32)
    monkeypatch.setattr(settings, "carrier_webhook_tokens", {"alpha": "token_alpha_12345"})

    async def mock_publish(*args, **kwargs):
        return QueuedWebhookMessage(
            message_id="msg-1",
            carrier_slug="SimCarrier Alpha",
            tracking_number="TRK100",
            raw_status="IN_TRANSIT",
            event_id="evt-1",
            occurred_at=None,
            location=None,
            content_type="application/json",
            enqueued_at="2026-11-03T10:00:00Z",
        )

    from app.routers import webhooks
    monkeypatch.setattr(webhooks.RabbitMQService, "publish_webhook_event", mock_publish)

    payload = {
        "event_id": "evt-1",
        "tracking_number": "TRK100",
        "status": "IN_TRANSIT",
    }

    # Pass valid carrier token
    resp = await sec_client.post(
        "/api/v1/webhooks/alpha",
        json=payload,
        headers={"X-Carrier-Token": "token_alpha_12345"},
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_webhook_auth_success_with_hmac_signature(sec_client, db_session, setup_carrier, monkeypatch):
    secret = "my_super_secret_webhook_key_32chars"
    monkeypatch.setattr(settings, "webhook_secret", secret)

    async def mock_publish(*args, **kwargs):
        return QueuedWebhookMessage(
            message_id="msg-1",
            carrier_slug="SimCarrier Alpha",
            tracking_number="TRK100",
            raw_status="IN_TRANSIT",
            event_id="evt-1",
            occurred_at=None,
            location=None,
            content_type="application/json",
            enqueued_at="2026-11-03T10:00:00Z",
        )

    from app.routers import webhooks
    monkeypatch.setattr(webhooks.RabbitMQService, "publish_webhook_event", mock_publish)

    body_bytes = b'{"event_id": "evt-1", "tracking_number": "TRK100", "status": "IN_TRANSIT"}'
    signature = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

    resp = await sec_client.post(
        "/api/v1/webhooks/alpha",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={signature}",
        },
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_webhook_auth_rejected_with_invalid_token(sec_client, db_session, setup_carrier, monkeypatch):
    monkeypatch.setattr(settings, "webhook_secret", "secret_" + "a" * 32)
    monkeypatch.setattr(settings, "carrier_webhook_tokens", {"alpha": "token_alpha_12345"})

    payload = {"event_id": "evt-1", "tracking_number": "TRK100", "status": "IN_TRANSIT"}

    resp = await sec_client.post(
        "/api/v1/webhooks/alpha",
        json=payload,
        headers={"X-Carrier-Token": "invalid_wrong_token"},
    )
    assert resp.status_code == 401
    assert "Unauthorized carrier webhook" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_auth_rejected_with_invalid_hmac(sec_client, db_session, setup_carrier, monkeypatch):
    secret = "my_super_secret_webhook_key_32chars"
    monkeypatch.setattr(settings, "webhook_secret", secret)

    body_bytes = b'{"event_id": "evt-1", "tracking_number": "TRK100", "status": "IN_TRANSIT"}'

    resp = await sec_client.post(
        "/api/v1/webhooks/alpha",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=forged_bad_signature",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_auth_rejected_in_production_without_secrets(sec_client, db_session, setup_carrier, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "webhook_secret", "")
    monkeypatch.setattr(settings, "carrier_webhook_tokens", {})
    monkeypatch.setattr(settings, "api_key", "")

    payload = {"event_id": "evt-1", "tracking_number": "TRK100", "status": "IN_TRANSIT"}

    resp = await sec_client.post(
        "/api/v1/webhooks/alpha",
        json=payload,
    )
    assert resp.status_code == 503
    assert "not configured in production" in resp.json()["detail"]
