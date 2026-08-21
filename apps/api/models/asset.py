import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional
from sqlalchemy import String, Enum, DateTime, ForeignKey, Integer, BigInteger, Float, func, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
try:
    from ..database import Base
except ImportError:
    from database import Base

class AssetType(str, PyEnum):
    image = "image"
    image_carousel = "image_carousel"
    audio = "audio"
    video = "video"

class AssetStatus(str, PyEnum):
    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    archived = "archived"

class ProcessingStatus(str, PyEnum):
    uploading = "uploading"
    processing = "processing"
    ready = "ready"
    failed = "failed"

class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType), nullable=False)
    status: Mapped[AssetStatus] = mapped_column(Enum(AssetStatus), default=AssetStatus.draft)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("folders.id"), nullable=True, index=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    keywords: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set only for assets ingested by scripts/ayon_client_watcher.py from an
    # Ayon DELIVERY_CLIENT_FREEFRAME delivery - the entity a client comment on this
    # asset should be relayed back to (see routers/comments.py / ayon_relay.py).
    ayon_project_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ayon_folder_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    ayon_task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ayon_version_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_assets_project_folder_deleted", "project_id", "folder_id", "deleted_at"),
    )

class AssetVersion(Base):
    __tablename__ = "asset_versions"
    __table_args__ = (UniqueConstraint("asset_id", "version_number", name="uq_asset_versions_asset_version"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Where THIS version's own source file was delivered/uploaded to -
    # independent of Asset.folder_id (the asset's own "primary" location,
    # set once at creation and otherwise unchanged). Different versions of
    # one asset can land in different folders (e.g. ayon_client_watcher.py
    # deliveries organized by date: 2026-08-20/.../v002 and
    # 2026-08-21/.../v003 both attach to the same asset for Compare
    # Versions, but each date's folder should still show what was actually
    # delivered there - see routers/assets.py list_assets's folder-scoped
    # "latest version" and routers/folders.py's item counts, both of which
    # read this instead of only Asset.folder_id). NULL on versions created
    # before this column existed - those fall back to Asset.folder_id.
    folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("folders.id"), nullable=True, index=True)
    processing_status: Mapped[ProcessingStatus] = mapped_column(Enum(ProcessingStatus), default=ProcessingStatus.uploading)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # The real Ayon version this specific delivered version is a copy of -
    # independent of Asset.ayon_version_id (set once, at first-ever-ingestion,
    # and never updated after). Every later version delivered onto the SAME
    # asset (v002, v003, ...) is a copy of a DIFFERENT Ayon version than v001
    # was, so without a per-version field here, ayon_relay.py had no way to
    # know which one a given comment was actually about and always fell back
    # to whatever Asset.ayon_version_id happened to be (v001's - the bug
    # reported 2026-08-21: "all comments go to v001"). ayon_task_id/
    # ayon_folder_id are NOT duplicated here since every version of one
    # asset is matched (find_existing_asset_id) on those SAME two ids by
    # construction - only the version id actually varies per version. NULL
    # on versions created before this column existed, or when the version
    # wasn't resolved back to a real Ayon entity - the relay still falls
    # back to the asset-level task/folder in that case.
    ayon_version_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

class FileType(str, PyEnum):
    image = "image"
    audio = "audio"
    video = "video"

class MediaFile(Base):
    __tablename__ = "media_files"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("asset_versions.id"), nullable=False, index=True)
    file_type: Mapped[FileType] = mapped_column(Enum(FileType), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    s3_key_raw: Mapped[str] = mapped_column(String(1000), nullable=False)
    s3_key_processed: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    s3_key_thumbnail: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sequence_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class CarouselItem(Base):
    __tablename__ = "carousel_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("asset_versions.id"), nullable=False)
    media_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("media_files.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
