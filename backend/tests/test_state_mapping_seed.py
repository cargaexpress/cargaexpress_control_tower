"""Initial seed must only use valid canonical statuses."""

import importlib.util
from pathlib import Path

from app.models.state_mapping import CANONICAL_STATUSES

SEED_FILE = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "c4a1209b7e6f_hu12_canonical_state_mapping.py"
)

SEED_12_FILE = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "bdb88a412f83_seed_all_12_carriers_and_mappings.py"
)


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_state_mapping_migration", SEED_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_12_carriers_seed_module():
    spec = importlib.util.spec_from_file_location("seed_all_12_carriers_migration", SEED_12_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_only_uses_valid_canonical_statuses():
    seed = _load_seed_module().SEED

    used = {canonical for mappings in seed.values() for canonical in mappings.values()}

    assert _load_seed_module().CANONICAL_STATUSES == (
        "CREATED",
        "PICKED_UP",
        "IN_TRANSIT",
        "OUT_FOR_DELIVERY",
        "EXCEPTION",
        "DELIVERED",
        "RETURNED",
        "LOST_OR_DAMAGED",
    )
    assert used <= set(CANONICAL_STATUSES)


def test_seed_defines_several_simulated_carriers_with_mappings():
    seed = _load_seed_module().SEED

    assert len(seed) >= 3
    assert all(len(mappings) >= 6 for mappings in seed.values())
    assert set(_load_seed_module().CANONICAL_STATUSES) <= {
        canonical for mappings in seed.values() for canonical in mappings.values()
    }


def test_seed_all_12_carriers_migration_contains_all_twelve():
    carrier_data = _load_12_carriers_seed_module().CARRIER_SEED_DATA
    assert len(carrier_data) == 12

    carrier_names = {c["name"] for c in carrier_data}
    expected_names = {
        "SimCarrier Alpha",
        "SimCarrier Beta",
        "SimCarrier Gamma",
        "SimCarrier Delta",
        "SimCarrier Epsilon",
        "SimCarrier A",
        "SimCarrier B",
        "SimCarrier C",
        "SimCarrier D",
        "TransExpress Logistics",
        "Rapido Andino",
        "Logistica 360",
    }
    assert carrier_names == expected_names

    # Verify each carrier has valid integration_type and mappings
    valid_types = {"webhook", "api", "file"}
    for c in carrier_data:
        assert c["integration_type"] in valid_types
        mappings = c["mappings"]
        assert len(mappings) >= 6
        for raw, canonical in mappings.items():
            assert canonical in CANONICAL_STATUSES
