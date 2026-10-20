"""Unit tests for webhook_decoders covering all 5 Type A carrier formats,

edge cases, missing fields, and error handling to ensure high test coverage.
"""

from datetime import UTC

import pytest

from app.services.webhook_decoders import (
    WebhookDecodeError,
    _parse_utc_iso,
    decode_alpha_json,
    decode_beta_nested_json,
    decode_carrier_payload,
    decode_delta_xml,
    decode_epsilon_form,
    decode_gamma_spanish_json,
)


def test_parse_utc_iso_variations():
    dt_with_z = _parse_utc_iso("2026-03-29T10:00:00Z")
    assert dt_with_z.tzinfo == UTC

    dt_without_tz = _parse_utc_iso("2026-03-29T10:00:00")
    assert dt_without_tz.tzinfo == UTC

    with pytest.raises(WebhookDecodeError, match="Invalid timestamp format"):
        _parse_utc_iso("invalid-timestamp")


def test_decode_alpha_json_success():
    payload = b'{"event_id": "evt-123", "tracking_number": "TRK-001", "status": "IN_TRANSIT", "occurred_at": "2026-03-29T12:00:00Z", "location": "Bogota"}'
    event = decode_alpha_json(payload)
    assert event.event_id == "evt-123"
    assert event.tracking_number == "TRK-001"
    assert event.raw_status == "IN_TRANSIT"
    assert event.location == "Bogota"
    assert event.occurred_at is not None


def test_decode_alpha_json_errors():
    with pytest.raises(WebhookDecodeError, match="missing required field"):
        decode_alpha_json(b'{"event_id": "evt-123"}')

    with pytest.raises(WebhookDecodeError, match="Alpha JSON decoding failed"):
        decode_alpha_json(b"not-json")


def test_decode_beta_nested_json_success():
    payload = b'{"eventId": "evt-beta", "shipment": {"trackingId": "TRK-BETA"}, "event": {"code": "PICKED_UP", "occurredAtEpochMs": 1700000000000}, "hub": "Medellin"}'
    event = decode_beta_nested_json(payload)
    assert event.event_id == "evt-beta"
    assert event.tracking_number == "TRK-BETA"
    assert event.raw_status == "PICKED_UP"
    assert event.location == "Medellin"
    assert event.occurred_at is not None


def test_decode_beta_nested_json_errors():
    with pytest.raises(WebhookDecodeError, match="missing required field"):
        decode_beta_nested_json(b'{"eventId": "evt-beta"}')

    with pytest.raises(WebhookDecodeError, match="decoding failed"):
        decode_beta_nested_json(b"invalid-json")


def test_decode_gamma_spanish_json_success():
    payload = b'{"id_evento": "evt-gam", "guia": "TRK-GAM", "estado": "EN_RUTA", "fecha": "2026-03-29T14:30:00Z", "ciudad": "Cali"}'
    event = decode_gamma_spanish_json(payload)
    assert event.event_id == "evt-gam"
    assert event.tracking_number == "TRK-GAM"
    assert event.raw_status == "EN_RUTA"
    assert event.location == "Cali"


def test_decode_gamma_spanish_json_errors():
    with pytest.raises(WebhookDecodeError, match="missing required field"):
        decode_gamma_spanish_json(b'{"id_evento": "evt-gam"}')

    with pytest.raises(WebhookDecodeError, match="decoding failed"):
        decode_gamma_spanish_json(b"invalid-json")


def test_decode_delta_xml_success():
    payload = b'<ShipmentEvent id="evt-del"><Tracking>TRK-DEL</Tracking><Status>OUT_DELIVERY</Status><Timestamp>20260329T100000Z</Timestamp><Location>Barranquilla</Location></ShipmentEvent>'
    event = decode_delta_xml(payload)
    assert event.event_id == "evt-del"
    assert event.tracking_number == "TRK-DEL"
    assert event.raw_status == "OUT_DELIVERY"
    assert event.location == "Barranquilla"
    assert event.occurred_at is not None


def test_decode_delta_xml_with_iso_timestamp():
    payload = b'<ShipmentEvent id="evt-del2"><Tracking>TRK-DEL2</Tracking><Status>DELIVERED</Status><Timestamp>2026-03-29T15:00:00Z</Timestamp></ShipmentEvent>'
    event = decode_delta_xml(payload)
    assert event.tracking_number == "TRK-DEL2"
    assert event.raw_status == "DELIVERED"
    assert event.occurred_at is not None


def test_decode_delta_xml_missing_elements_raises():
    payload = b'<ShipmentEvent id="evt-del"><Location>Nowhere</Location></ShipmentEvent>'
    with pytest.raises(WebhookDecodeError, match="missing Tracking or Status element"):
        decode_delta_xml(payload)


def test_decode_delta_xml_invalid_syntax_raises():
    with pytest.raises(WebhookDecodeError, match="Delta XML decoding failed"):
        decode_delta_xml(b"<UnclosedTag>")


def test_decode_epsilon_form_success():
    payload = b"evt=evt-eps&awb=TRK-EPS&state=DELIVERED&ts=1700000000&city=Cartagena"
    event = decode_epsilon_form(payload)
    assert event.event_id == "evt-eps"
    assert event.tracking_number == "TRK-EPS"
    assert event.raw_status == "DELIVERED"
    assert event.location == "Cartagena"
    assert event.occurred_at is not None


def test_decode_epsilon_form_errors():
    with pytest.raises(WebhookDecodeError, match="missing required field"):
        decode_epsilon_form(b"evt=evt-eps&city=Cartagena")

    with pytest.raises(WebhookDecodeError, match="decoding failed"):
        decode_epsilon_form(b"\xff\xfe\xfd")


def test_decode_carrier_payload_routing():
    alpha = decode_carrier_payload(
        "simcarrier-alpha",
        "application/json",
        b'{"event_id": "1", "tracking_number": "T1", "status": "OK"}',
    )
    assert alpha.tracking_number == "T1"

    beta = decode_carrier_payload(
        "simcarrier-beta",
        "application/json",
        b'{"eventId": "2", "shipment": {"trackingId": "T2"}, "event": {"code": "OK"}}',
    )
    assert beta.tracking_number == "T2"

    gamma = decode_carrier_payload(
        "simcarrier-gamma", "application/json", b'{"id_evento": "3", "guia": "T3", "estado": "OK"}'
    )
    assert gamma.tracking_number == "T3"

    delta = decode_carrier_payload(
        "simcarrier-delta",
        "application/xml",
        b'<ShipmentEvent id="4"><Tracking>T4</Tracking><Status>OK</Status></ShipmentEvent>',
    )
    assert delta.tracking_number == "T4"

    epsilon = decode_carrier_payload(
        "simcarrier-epsilon", "application/x-www-form-urlencoded", b"evt=5&awb=T5&state=OK"
    )
    assert epsilon.tracking_number == "T5"


def test_decode_carrier_payload_fallbacks():
    # By content-type XML
    xml_ev = decode_carrier_payload(
        "custom-carrier",
        "application/xml",
        b'<ShipmentEvent id="x"><Tracking>TX</Tracking><Status>OK</Status></ShipmentEvent>',
    )
    assert xml_ev.tracking_number == "TX"

    # By content-type Form
    form_ev = decode_carrier_payload(
        "custom-carrier", "application/x-www-form-urlencoded", b"evt=x&awb=TX2&state=OK"
    )
    assert form_ev.tracking_number == "TX2"

    # Generic JSON fallback
    generic_ev = decode_carrier_payload(
        "custom-carrier", "application/json", b'{"tracking_number": "TG", "status": "DELIVERED"}'
    )
    assert generic_ev.tracking_number == "TG"
    assert generic_ev.raw_status == "DELIVERED"

    # Unsupported format raises
    with pytest.raises(WebhookDecodeError, match="Unsupported payload format"):
        decode_carrier_payload("custom-carrier", "text/plain", b"invalid payload")
