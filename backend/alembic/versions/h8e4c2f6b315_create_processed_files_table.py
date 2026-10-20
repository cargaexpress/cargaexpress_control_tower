"""Create processed_files table for Type C batch file tracking and deduplication.

Revision ID: h8e4c2f6b315
Revises: g7d3b1e5a204
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8e4c2f6b315"
down_revision: Union[str, None] = "g7d3b1e5a204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processed_files",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("carrier_name", sa.String(), nullable=False),
        sa.Column("total_records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("anomalies_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("filename", name="uq_processed_files_filename"),
    )
    op.create_index("ix_processed_files_filename", "processed_files", ["filename"])
    op.create_index("ix_processed_files_file_hash", "processed_files", ["file_hash"])
    op.create_index("ix_processed_files_carrier_name", "processed_files", ["carrier_name"])


def downgrade() -> None:
    op.drop_index("ix_processed_files_carrier_name", table_name="processed_files")
    op.drop_index("ix_processed_files_file_hash", table_name="processed_files")
    op.drop_index("ix_processed_files_filename", table_name="processed_files")
    op.drop_table("processed_files")
