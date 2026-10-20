from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProcessedFile(Base):
    """Tracks ingested batch files to ensure idempotency and prevent duplicate processing (CT-08)."""

    __tablename__ = "processed_files"
    __table_args__ = (
        Index("ix_processed_files_filename", "filename"),
        Index("ix_processed_files_file_hash", "file_hash"),
        Index("ix_processed_files_carrier_name", "carrier_name"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    filename: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    carrier_name: Mapped[str] = mapped_column(String, nullable=False)
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    valid_records: Mapped[int] = mapped_column(Integer, default=0)
    anomalies_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
