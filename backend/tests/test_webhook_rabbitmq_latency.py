"""Subtask 4: Measure the endpoint's p95 latency after the RabbitMQ queuing change.

Acceptance Criteria:
- The webhook endpoint responds in less than 200 ms (RNF-01).
- The message remains in the queue for later processing.
"""

import asyncio
import statistics
import time

import pytest

from app.main import app
from app.models.carrier import Carrier
from app.services.rabbitmq_service import (
    QueuedWebhookMessage,
    get_rabbitmq_service,
)


@pytest.mark.asyncio
async def test_webhook_endpoint_p95_latency_under_200ms(client, db_session):
    """Fires 100 requests to measure p95 response time and verify queue retention."""
    carrier = Carrier(
        carrier_id=1,
        name="SimCarrier Alpha",
        integration_type="webhook",
        status="active",
    )
    db_session.add(carrier)
    await db_session.commit()

    enqueued_messages: list[QueuedWebhookMessage] = []

    class MockRabbitMQService:
        async def publish_webhook_event(self, carrier_slug, event, content_type="application/json"):
            # Simulate real network async I/O to RabbitMQ broker (~1-2 ms)
            await asyncio.sleep(0.001)
            msg = QueuedWebhookMessage(
                message_id=f"msg-{len(enqueued_messages) + 1}",
                carrier_slug=carrier_slug,
                tracking_number=event.tracking_number,
                raw_status=event.raw_status,
                event_id=event.event_id,
                occurred_at=None,
                location=event.location,
                content_type=content_type,
                enqueued_at="2026-10-20T12:00:00Z",
            )
            enqueued_messages.append(msg)
            return msg

    app.dependency_overrides[get_rabbitmq_service] = lambda: MockRabbitMQService()

    latencies_ms: list[float] = []
    payload = {
        "event_id": "evt-bench-01",
        "tracking_number": "TRK-BENCH-01",
        "status": "IN_TRANSIT",
        "occurred_at": "2026-03-29T10:00:00Z",
        "location": "Main Hub",
    }

    # Fire 100 requests
    num_requests = 100
    for i in range(num_requests):
        payload["tracking_number"] = f"TRK-BENCH-{i:03d}"
        t0 = time.perf_counter()
        response = await client.post(
            "/api/v1/webhooks/alpha",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        assert body["tracking_number"] == f"TRK-BENCH-{i:03d}"

    # Clean up override
    app.dependency_overrides.pop(get_rabbitmq_service, None)

    # Calculate percentiles
    sorted_latencies = sorted(latencies_ms)
    p50 = statistics.median(sorted_latencies)
    p90 = sorted_latencies[int(num_requests * 0.90)]
    p95 = sorted_latencies[int(num_requests * 0.95)]
    p99 = sorted_latencies[int(num_requests * 0.99)]
    min_lat = min(sorted_latencies)
    max_lat = max(sorted_latencies)
    avg_lat = statistics.mean(sorted_latencies)

    print(
        f"\n[LATENCY REPORT - RNF-01]\n"
        f"Total requests: {num_requests}\n"
        f"Min latency:   {min_lat:.2f} ms\n"
        f"Average:       {avg_lat:.2f} ms\n"
        f"p50 (Median):  {p50:.2f} ms\n"
        f"p90:           {p90:.2f} ms\n"
        f"p95:           {p95:.2f} ms (Target < 200 ms)\n"
        f"p99:           {p99:.2f} ms\n"
        f"Max latency:   {max_lat:.2f} ms\n"
    )

    # Acceptance Criteria: Endpoint responds in less than 200 ms
    assert p95 < 200.0, f"p95 latency {p95:.2f}ms exceeded 200ms SLA target"

    # Acceptance Criteria: Messages remain in queue for later processing
    assert len(enqueued_messages) == num_requests
    assert enqueued_messages[0].tracking_number == "TRK-BENCH-000"
    assert enqueued_messages[-1].tracking_number == "TRK-BENCH-099"
