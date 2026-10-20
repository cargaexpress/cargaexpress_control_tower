import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from xml.etree import ElementTree as ET


class WebhookDecodeError(ValueError):
    """Raised when an incoming webhook payload cannot be parsed or validated."""


@dataclass(slots=True)
class DecodedWebhookEvent:
    """Standardized event extracted from any of the 5 carrier formats."""

    event_id: str
    tracking_number: str
    raw_status: str
    occurred_at: datetime | None = None
    location: str | None = None


EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _parse_utc_iso(timestamp_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(timestamp_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception as exc:
        raise WebhookDecodeError(f"Invalid timestamp format: {timestamp_str}") from exc


def decode_alpha_json(body: bytes) -> DecodedWebhookEvent:
    """Alpha: Flat JSON (snake_case, ISO-8601 UTC timestamp)."""
    try:
        data = json.loads(body.decode("utf-8"))
        return DecodedWebhookEvent(
            event_id=str(data["event_id"]),
            tracking_number=str(data["tracking_number"]),
            raw_status=str(data["status"]),
            occurred_at=_parse_utc_iso(data["occurred_at"]) if "occurred_at" in data else None,
            location=data.get("location"),
        )
    except KeyError as exc:
        raise WebhookDecodeError(f"Alpha format missing required field: {exc}") from exc
    except Exception as exc:
        raise WebhookDecodeError(f"Alpha JSON decoding failed: {exc}") from exc


def decode_beta_nested_json(body: bytes) -> DecodedWebhookEvent:
    """Beta: Nested JSON (camelCase, numeric epoch milliseconds)."""
    try:
        data = json.loads(body.decode("utf-8"))
        shipment = data.get("shipment", {})
        event = data.get("event", {})
        epoch_ms = event.get("occurredAtEpochMs")
        occurred_at = (
            EPOCH + timedelta(milliseconds=int(epoch_ms)) if epoch_ms is not None else None
        )

        return DecodedWebhookEvent(
            event_id=str(data["eventId"]),
            tracking_number=str(shipment["trackingId"]),
            raw_status=str(event["code"]),
            occurred_at=occurred_at,
            location=data.get("hub"),
        )
    except KeyError as exc:
        raise WebhookDecodeError(f"Beta format missing required field: {exc}") from exc
    except Exception as exc:
        raise WebhookDecodeError(f"Beta nested JSON decoding failed: {exc}") from exc


def decode_gamma_spanish_json(body: bytes) -> DecodedWebhookEvent:
    """Gamma: Spanish JSON (local time with offset)."""
    try:
        data = json.loads(body.decode("utf-8"))
        return DecodedWebhookEvent(
            event_id=str(data["id_evento"]),
            tracking_number=str(data["guia"]),
            raw_status=str(data["estado"]),
            occurred_at=_parse_utc_iso(data["fecha"]) if "fecha" in data else None,
            location=data.get("ciudad"),
        )
    except KeyError as exc:
        raise WebhookDecodeError(f"Gamma format missing required field: {exc}") from exc
    except Exception as exc:
        raise WebhookDecodeError(f"Gamma Spanish JSON decoding failed: {exc}") from exc


def decode_delta_xml(body: bytes) -> DecodedWebhookEvent:
    """Delta: Compact XML (<ShipmentEvent id="..."><Tracking>...</Tracking>...)."""
    try:
        root = ET.fromstring(body.decode("utf-8"))
        event_id = root.attrib.get("id", "")
        tracking = root.findtext("Tracking", "")
        status = root.findtext("Status", "")
        timestamp_str = root.findtext("Timestamp")
        location = root.findtext("Location")

        if not tracking or not status:
            raise WebhookDecodeError("Delta XML missing Tracking or Status element")

        occurred_at = None
        if timestamp_str:
            try:
                occurred_at = datetime.strptime(timestamp_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            except ValueError:
                occurred_at = _parse_utc_iso(timestamp_str)

        return DecodedWebhookEvent(
            event_id=event_id,
            tracking_number=tracking,
            raw_status=status,
            occurred_at=occurred_at,
            location=location,
        )
    except WebhookDecodeError:
        raise
    except Exception as exc:
        raise WebhookDecodeError(f"Delta XML decoding failed: {exc}") from exc


def decode_epsilon_form(body: bytes) -> DecodedWebhookEvent:
    """Epsilon: x-www-form-urlencoded (epoch seconds)."""
    try:
        raw = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        fields = {k: v[0] for k, v in raw.items()}
        ts = fields.get("ts")
        occurred_at = EPOCH + timedelta(seconds=int(ts)) if ts and ts.isdigit() else None

        return DecodedWebhookEvent(
            event_id=fields.get("evt", ""),
            tracking_number=fields["awb"],
            raw_status=fields["state"],
            occurred_at=occurred_at,
            location=fields.get("city"),
        )
    except KeyError as exc:
        raise WebhookDecodeError(f"Epsilon form missing required field: {exc}") from exc
    except Exception as exc:
        raise WebhookDecodeError(f"Epsilon form decoding failed: {exc}") from exc


def decode_carrier_payload(
    carrier_slug: str, content_type: str, body: bytes
) -> DecodedWebhookEvent:
    """Dispatches payload decoding based on carrier slug and/or Content-Type."""
    slug = carrier_slug.lower().strip()

    # Match by carrier identity from type_A_simulation_data
    if "alpha" in slug:
        return decode_alpha_json(body)
    elif "beta" in slug:
        return decode_beta_nested_json(body)
    elif "gamma" in slug:
        return decode_gamma_spanish_json(body)
    elif "delta" in slug:
        return decode_delta_xml(body)
    elif "epsilon" in slug:
        return decode_epsilon_form(body)

    # Fallback inspection by content-type
    ct = content_type.lower()
    if "xml" in ct:
        return decode_delta_xml(body)
    if "x-www-form-urlencoded" in ct:
        return decode_epsilon_form(body)

    # Fallback generic JSON
    try:
        data = json.loads(body.decode("utf-8"))
        tracking = data.get("tracking_number") or data.get("trackingId") or data.get("guia")
        status = data.get("status") or data.get("code") or data.get("estado")
        if tracking and status:
            return DecodedWebhookEvent(
                event_id=str(data.get("event_id", data.get("eventId", ""))),
                tracking_number=str(tracking),
                raw_status=str(status),
                occurred_at=None,
                location=data.get("location"),
            )
    except Exception:
        pass

    raise WebhookDecodeError(f"Unsupported payload format for carrier '{carrier_slug}'")
