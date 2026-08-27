from pydantic import BaseModel, Field


class InstanceSettingsUpdate(BaseModel):
    # Upper bound = PostgreSQL BigInteger max (2**63 - 1); rejects overflow with 422 instead of a 500.
    storage_limit_bytes: int | None = Field(default=None, ge=0, le=9223372036854775807)
    staff_email_domains: list[str] | None = None
    workspace_name: str | None = Field(default=None, min_length=1, max_length=255)
    ayon_relay_paused: bool | None = None
    # Client Sharing rules - see routers/share.py's _apply_client_sharing_rules.
    client_share_expiry_days: int | None = Field(default=None, ge=1, le=365)
    client_share_expiry_enforced: bool | None = None
    client_share_watermark_enforced: bool | None = None


class InstanceSettingsResponse(BaseModel):
    # Curated per role. Today member and admin see the same fields; future admin-only
    # fields must be excluded from the member response rather than dumping the row.
    storage_limit_bytes: int
    storage_used_bytes: int
    staff_email_domains: list[str] = []
    workspace_name: str = "FreeFrame"
    ayon_relay_paused: bool = False
    client_share_expiry_days: int = 7
    client_share_expiry_enforced: bool = True
    client_share_watermark_enforced: bool = True
