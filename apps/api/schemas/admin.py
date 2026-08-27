import uuid

from pydantic import BaseModel, EmailStr, Field


class PurgeStartResponse(BaseModel):
    """Response for the async manual purge trigger."""
    status: str
    detail: str


class EmailStatusResponse(BaseModel):
    """Admin Settings -> Email: current mail configuration, no secrets."""
    provider: str
    configured: bool
    from_address: str
    from_name: str
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_use_tls: bool | None = None


class SendTestEmailRequest(BaseModel):
    to_email: EmailStr


class AyonConnectionResponse(BaseModel):
    """Admin Settings -> Ayon Projects: current Ayon connection. The API key is
    never returned raw, only masked (last 4 chars) so the admin can confirm
    which key is active without re-exposing it."""
    ayon_url: str | None = None
    api_key_masked: str | None = None
    # "database": overridden here via PUT. "launcher": falling back to the
    # Pinokio launcher's AYON_URL/AYON_API_KEY env config. "unset": neither is configured.
    source: str


class AyonConnectionUpdate(BaseModel):
    # None = leave unchanged. "" = clear the override and fall back to the launcher's env config.
    ayon_url: str | None = None
    ayon_api_key: str | None = None


class ProjectPurgePreviewResponse(BaseModel):
    """Admin danger-zone: what a permanent purge would remove, shown before the admin confirms."""
    project_name: str
    counts: dict[str, int]
    nas_delivery_path: str | None = None


class ProjectPurgeNowRequest(BaseModel):
    # Must exactly match the project's current name - a typed confirmation gate
    # (mirrors GitHub's repo-delete UX) enforced server-side, not just client-side.
    confirm_name: str


class ProjectPurgeNowResponse(BaseModel):
    status: str
    counts: dict
    nas_moved_to: str | None = None


class AdminCreateUserRequest(BaseModel):
    """Admin Users -> "Create User": makes an active account directly
    (no invite link/magic code), with a credentials email sent to the
    new user. See routers/admin.py create_user."""
    email: EmailStr
    name: str
    password: str = Field(min_length=8)
    cc_emails: list[EmailStr] = []


class UserProjectAccessItem(BaseModel):
    """One row in the Admin -> Users -> "Ayon Project" modal: a project this
    (non-staff/client) user could be given access to, and whether they
    currently have it."""
    project_id: uuid.UUID
    project_name: str
    ayon_project_name: str | None = None
    is_member: bool


class SetUserProjectAccessRequest(BaseModel):
    """Full-replace: the user ends up a member of exactly these projects
    (added to any missing, removed from any not listed) - simplest mapping
    for a checkbox-list modal."""
    project_ids: list[uuid.UUID]


class AdminShareLinkItem(BaseModel):
    """One row in Settings -> Admin -> Share Links: every share link across
    every project, for instance-wide oversight/cancellation - see
    routers/admin.py list_all_share_links."""
    id: uuid.UUID
    token: str
    title: str
    share_type: str  # "asset" | "folder" | "project"
    project_id: uuid.UUID
    project_name: str
    created_by_name: str
    created_by_email: str
    is_client: bool
    is_enabled: bool
    visibility: str
    permission: str
    allow_download: bool
    show_watermark: bool
    expires_at: str | None = None
    created_at: str
