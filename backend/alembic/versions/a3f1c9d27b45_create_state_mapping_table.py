"""Create state_mapping table

Revision ID: a3f1c9d27b45
Revises: dee4876a63bd
Create Date: 2026-10-08 12:46:57.062950

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3f1c9d27b45'
down_revision: str | None = 'dee4876a63bd'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('state_mapping',
    sa.Column('mapping_id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('carrier_id', sa.BigInteger(), nullable=False),
    sa.Column('source_status', sa.String(), nullable=False),
    sa.Column('canonical_status', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['carrier_id'], ['carriers.carrier_id'], ),
    sa.PrimaryKeyConstraint('mapping_id'),
    sa.UniqueConstraint('carrier_id', 'source_status', name='uq_state_mapping_carrier_source')
    )


def downgrade() -> None:
    op.drop_table('state_mapping')
