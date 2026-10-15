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


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_state_mapping_migration", SEED_FILE)
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
