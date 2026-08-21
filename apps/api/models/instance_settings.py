import uuid
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
try:
    from ..database import Base
except ImportError:
    from database import Base


class InstanceSettings(Base):
    """Single-row table holding instance-wide (deployment-level) settings.

    Singleton: exactly one row, created lazily via get_or_create in the router.
    storage_limit_bytes == 0 means unlimited (matches MAX_UPLOAD_BYTES).
    """
    __tablename__ = "instance_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    storage_limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    # Email domains treated as internal/staff (see services/permissions.py
    # is_staff_user). Anyone logging in with any other domain is a client
    # account - reserved for future CLIENT_SHARE-only asset filtering.
    staff_email_domains: Mapped[list] = mapped_column(
        JSON, nullable=False, server_default='["mnm.local", "methodnmadness.com"]'
    )
    # Shown in the sidebar (Settings > Branding > Workspace name) and
    # available server-side as the {{site_name}} email template variable -
    # previously client-side-only (localStorage), so emails couldn't
    # reference it at all.
    workspace_name: Mapped[str] = mapped_column(String(255), nullable=False, server_default="FreeFrame")
    # Global kill switch for scripts/ayon_relay.py's automatic relaying -
    # checked by the daemon itself (is_relay_paused), not enforced here.
    # Manual per-comment shares (POST /comments/{id}/share-to-ayon) always
    # bypass this, by design - see the sidebar toggle and comment "..." menu.
    ayon_relay_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # Optional override for the Pinokio-launcher-provided AYON_URL/AYON_API_KEY
    # env vars (see config.py) - lets an admin repoint or rotate the Ayon
    # connection from Settings > Admin > Ayon Projects without restarting the
    # launcher. NULL means "fall back to the launcher's env config" (see
    # services/ayon_service.py._resolve_credentials). Stored in plaintext, not
    # via services/crypto_service.py's Fernet encryption: that key is derived
    # from JWT_SECRET, which start.js regenerates on every launcher restart,
    # so an encrypted key would become undecryptable on the very next restart.
    ayon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ayon_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
