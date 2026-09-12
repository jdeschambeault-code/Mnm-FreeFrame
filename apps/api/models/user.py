import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional
from sqlalchemy import String, Enum, DateTime, JSON, func, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
try:
    from ..database import Base
except ImportError:
    from database import Base

class UserStatus(str, PyEnum):
    active = "active"
    deactivated = "deactivated"
    pending_invite = "pending_invite"
    pending_verification = "pending_verification"

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Set on first "Sign in with Google" for this account - find-or-create by
    # email in routers/auth.py's /auth/google/callback. NULL for every other
    # login method (magic-code, password, invite); password_hash can coexist
    # (a Google-provisioned account can still set a password later via the
    # normal set-password flow).
    google_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.active)
    is_superadmin: Mapped[bool] = mapped_column(default=False)
    email_verified: Mapped[bool] = mapped_column(default=False)
    invite_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    invite_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    preferences: Mapped[dict] = mapped_column(JSON, nullable=False, server_default='{}')
    token_version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    # Set when an admin creates the account with a password directly
    # (POST /admin/users) - that password traveled over email in plaintext,
    # so the account is forced through the same set-new-password screen a
    # fresh invite uses, before it can be used normally.
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Set on every successful login (password, magic-code, and invite-accept -
    # see routers/auth.py) - NULL until the account's first login. Powers the
    # "Joined" column on Settings > Admin > Users, which shows this (not
    # created_at) since an invited-but-never-logged-in account's created_at
    # isn't actually meaningful activity to show an admin.
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class GuestUser(Base):
    __tablename__ = "guest_users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
