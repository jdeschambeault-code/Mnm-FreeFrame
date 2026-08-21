import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional
from sqlalchemy import String, Boolean, Enum, DateTime, ForeignKey, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
try:
    from ..database import Base
except ImportError:
    from database import Base

class ProjectType(str, PyEnum):
    personal = "personal"
    team = "team"

class ProjectRole(str, PyEnum):
    owner = "owner"
    editor = "editor"
    reviewer = "reviewer"
    viewer = "viewer"

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    project_type: Mapped[ProjectType] = mapped_column(Enum(ProjectType), default=ProjectType.personal)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    poster_s3_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Set when this project was activated from an Ayon project via
    # /admin/ayon/projects/{name}/activate. Unique so at most one FreeFrame
    # project maps to a given Ayon project.
    ayon_project_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[ProjectRole] = mapped_column(Enum(ProjectRole), default=ProjectRole.viewer)
    invited_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class UserHiddenProject(Base):
    """Lets a staff user (see services/permissions.is_staff_user) personally
    opt out of seeing a specific project in their own project list, without
    affecting anyone else or the project itself - staff see every non-
    deleted project by default (routers/projects.py list_projects), unlike
    non-staff/client users, who only ever see projects they're an explicit
    ProjectMember of. Irrelevant for non-staff users - they have no "sees
    everything by default" behavior to opt out of."""
    __tablename__ = "user_hidden_projects"
    __table_args__ = (UniqueConstraint("user_id", "project_id", name="uq_user_hidden_projects_user_project"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    hidden_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
