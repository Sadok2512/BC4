from datetime import datetime
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class NmfImportJob(Base):
    __tablename__ = 'nmf_import_jobs'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    files: Mapped[list] = mapped_column(JSON, nullable=False)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # NULL only identifies jobs created before migration 0061. Every new job
    # receives an immutable snapshot in import_jobs.enqueue().
    decode_level: Mapped[str | None] = mapped_column(String, nullable=True)
    binning_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    temporal_resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    spatial_bin_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aggregation_contract_version: Mapped[str | None] = mapped_column(String, nullable=True)
    decoder_version: Mapped[str | None] = mapped_column(String, nullable=True)
