"""El seed inicial solo debe usar estados canónicos válidos."""

import importlib.util
from pathlib import Path

from app.models.state_mapping import CANONICAL_STATUSES

SEED_FILE = next(
    (Path(__file__).resolve().parent.parent / "alembic" / "versions").glob("*_seed_state_mapping_*.py")
)


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_state_mapping_migration", SEED_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_only_uses_valid_canonical_statuses():
    seed = _load_seed_module().SEED

    used = {canonical for mappings in seed.values() for canonical in mappings.values()}

    assert used <= set(CANONICAL_STATUSES)


def test_seed_defines_several_simulated_carriers_with_mappings():
    seed = _load_seed_module().SEED

    assert len(seed) >= 3
    assert all(len(mappings) > 0 for mappings in seed.values())
