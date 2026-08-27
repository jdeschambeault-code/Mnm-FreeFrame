"""Admin endpoints for user management."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.user import User, UserStatus
from ..models.project import Project, ProjectMember, ProjectRole
from ..models.instance_settings import InstanceSettings
from ..schemas.auth import UserResponse, AdminUserResponse, UpdateUserRoleRequest
from .users import require_admin, require_staff_or_admin
from ..services.auth_service import hash_password, get_user_by_email
from ..tasks.celery_app import send_task_safe
from ..tasks.cleanup_tasks import cleanup_soft_deleted
from ..tasks.email_tasks import send_credentials_email
from sqlalchemy import text
from dataclasses import asdict

from ..schemas.admin import (
    PurgeStartResponse,
    UserProjectAccessItem,
    SetUserProjectAccessRequest,
    AdminCreateUserRequest,
    EmailStatusResponse,
    SendTestEmailRequest,
    AyonConnectionResponse,
    AyonConnectionUpdate,
    ProjectPurgePreviewResponse,
    ProjectPurgeNowRequest,
    ProjectPurgeNowResponse,
    AdminShareLinkItem,
)
from ..services.email_service import email_service, mail_is_configured
from ..schemas.ayon import AyonProjectSummary, ActivateAyonProjectRequest
from ..schemas.project import ProjectResponse
from ..services import ayon_service
from ..config import settings
from .instance_settings import get_or_create_instance_settings
from ..tasks.cleanup_tasks import _purge_project, PurgeCounts

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[AdminUserResponse])
def list_all_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all users in the system. Only accessible by admins."""
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access this endpoint"
        )

    users = db.query(User).filter(User.deleted_at.is_(None)).all()
    return users


@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    body: AdminCreateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an active account directly with the given password (skips the
    invite/magic-code flow) and email the credentials. The account is forced
    through the set-new-password screen on its first login."""
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create users",
        )

    if get_user_by_email(db, body.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    # email is a raw unique DB constraint, not scoped to deleted_at IS NULL -
    # a previously-deleted account still holds this email's slot, so a plain
    # insert here would violate it and crash (mirrors the same fix on
    # activate_ayon_project for uq_projects_ayon_project_name below).
    # Reactivate that row instead of trying to create a duplicate.
    user = db.query(User).filter(
        User.email == body.email, User.deleted_at.is_not(None)
    ).order_by(User.deleted_at.desc()).first()
    if user:
        user.deleted_at = None
        user.name = body.name
        user.password_hash = hash_password(body.password)
        user.status = UserStatus.active
        user.email_verified = True
        user.must_change_password = True
        user.is_superadmin = False  # don't silently resurrect prior admin rights
        user.invite_token = None
        user.invite_token_expires_at = None
        user.token_version += 1  # invalidate any tokens from its previous life
    else:
        user = User(
            email=body.email,
            name=body.name,
            password_hash=hash_password(body.password),
            status=UserStatus.active,
            email_verified=True,
            must_change_password=True,
        )
        db.add(user)
    db.commit()
    db.refresh(user)

    instance_row = db.query(InstanceSettings).first()
    site_name = (instance_row.workspace_name if instance_row else None) or "FreeFrame"
    send_task_safe(
        send_credentials_email,
        user.email,
        user.name,
        body.password,
        site_name,
        settings.frontend_url,
        cc_emails=body.cc_emails or None,
    )

    return user

@router.patch("/users/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deactivate a user. Admins cannot deactivate themselves."""
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can deactivate users"
        )

    # Prevent admin from deactivating themselves
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate yourself"
        )

    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.status = UserStatus.deactivated
    db.commit()
    db.refresh(user)
    return user

@router.patch("/users/{user_id}/reactivate", response_model=UserResponse)
def reactivate_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reactivate a deactivated user. Only accessible by admins."""
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can reactivate users"
        )

    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.status = UserStatus.active
    db.commit()
    db.refresh(user)
    return user

@router.patch("/users/{user_id}/role", response_model=UserResponse)
def update_user_role(
    user_id: uuid.UUID,
    body: UpdateUserRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Promote or demote a user to/from admin role. Only accessible by admins."""
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can change user roles"
        )

    # Prevent admin from removing their own admin role
    if user_id == current_user.id and not body.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove your own admin role"
        )

    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_superadmin = body.is_admin
    db.commit()
    db.refresh(user)
    return user


# ── Per-user Ayon project access (Admin -> Users -> "Ayon Project") ─────────────
# Staff users (services.permissions.is_staff_user) already see every project
# by default (routers/projects.py list_projects) and self-manage exceptions
# via "My Ayon Projects" (/projects/{id}/hide - /unhide) - these two are for
# the opposite case: a non-staff/client user, who only ever sees projects
# they're an explicit ProjectMember of, and has no self-service page for it.
# Rather than requiring an admin to open each project's own Members page one
# at a time, this lets them set one user's full project list in one place.

@router.get("/users/{user_id}/projects", response_model=list[UserProjectAccessItem])
def get_user_project_access(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    member_project_ids = {
        m.project_id for m in db.query(ProjectMember.project_id).filter(
            ProjectMember.user_id == user_id, ProjectMember.deleted_at.is_(None)
        ).all()
    }
    projects = db.query(Project).filter(Project.deleted_at.is_(None)).order_by(Project.name).all()
    return [
        UserProjectAccessItem(
            project_id=p.id,
            project_name=p.name,
            ayon_project_name=p.ayon_project_name,
            is_member=p.id in member_project_ids,
        )
        for p in projects
    ]


@router.put("/users/{user_id}/projects", response_model=list[UserProjectAccessItem])
def set_user_project_access(
    user_id: uuid.UUID,
    body: SetUserProjectAccessRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    valid_project_ids = {
        p.id for p in db.query(Project.id).filter(
            Project.id.in_(body.project_ids), Project.deleted_at.is_(None)
        ).all()
    }
    # Includes soft-deleted rows too (unlike everywhere else that reads
    # membership) - the (project_id, user_id) unique constraint doesn't
    # account for deleted_at, so a project this user had access to before,
    # had revoked, and is now being re-granted must REVIVE that same row
    # (clear deleted_at) rather than INSERT a new one, which would collide
    # with the still-present soft-deleted row and 500.
    existing = {
        m.project_id: m for m in db.query(ProjectMember).filter(
            ProjectMember.user_id == user_id
        ).all()
    }

    for project_id in valid_project_ids - existing.keys():
        db.add(ProjectMember(project_id=project_id, user_id=user_id, role=ProjectRole.reviewer, invited_by=current_user.id))
    for project_id, member in existing.items():
        if project_id in valid_project_ids:
            member.deleted_at = None
        else:
            member.deleted_at = datetime.now(timezone.utc)
    db.commit()

    return get_user_project_access(user_id, db, current_user)


@router.post("/purge", response_model=PurgeStartResponse, status_code=status.HTTP_202_ACCEPTED)
def purge_now(current_user: User = Depends(require_admin)):
    """Trigger the retention-window garbage collector to run now, in the background.

    Superadmin only. Enqueues the same `cleanup_soft_deleted` task the daily beat runs, so the
    request returns immediately instead of blocking on a potentially long cascade + S3 deletes.
    Reclaimed counts are logged by the worker. If a purge is already running (e.g. the daily beat),
    the advisory lock serializes purges and this enqueued run is skipped rather than double-cascading,
    so a 202 here means "enqueued", not "a fresh run happened".
    """
    send_task_safe(cleanup_soft_deleted)
    return PurgeStartResponse(
        status="started",
        detail="Retention garbage collection is running in the background; see worker logs for reclaimed counts.",
    )


# ── Danger zone: permanent single-project purge (DB + S3 + NAS) ─────────────
# Unlike /purge above (a retention-window sweep over already-soft-deleted
# projects), this targets one specific project - active or not - right now.

@router.get("/projects/{project_id}/purge-preview", response_model=ProjectPurgePreviewResponse)
def purge_project_preview(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pid = str(project_id)
    counts = {
        "assets": db.execute(text("SELECT count(*) FROM assets WHERE project_id=:pid"), {"pid": pid}).scalar(),
        "folders": db.execute(text("SELECT count(*) FROM folders WHERE project_id=:pid"), {"pid": pid}).scalar(),
        "comments": db.execute(
            text("SELECT count(*) FROM comments c JOIN assets a ON c.asset_id = a.id WHERE a.project_id=:pid"),
            {"pid": pid},
        ).scalar(),
        "share_links": db.execute(text("SELECT count(*) FROM share_links WHERE project_id=:pid"), {"pid": pid}).scalar(),
        "members": db.execute(text("SELECT count(*) FROM project_members WHERE project_id=:pid"), {"pid": pid}).scalar(),
    }

    nas_delivery_path = None
    if project.ayon_project_name:
        try:
            nas_delivery_path = ayon_service.get_project_client_delivery_path(project.ayon_project_name)
        except Exception:
            nas_delivery_path = None

    return ProjectPurgePreviewResponse(project_name=project.name, counts=counts, nas_delivery_path=nas_delivery_path)


@router.post("/projects/{project_id}/purge-now", response_model=ProjectPurgeNowResponse)
def purge_project_now(
    project_id: uuid.UUID,
    body: ProjectPurgeNowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Permanently deletes one project's FreeFrame DB rows + S3 objects (via
    the same cascade the retention GC uses, see tasks/cleanup_tasks.py
    _purge_project), and best-effort trash-moves its NAS client-delivery
    folder (not erased - see ayon_service.trash_move_client_delivery).
    Irreversible on the FreeFrame side. Requires typing the exact project
    name as confirm_name - enforced here, not just in the frontend dialog."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if body.confirm_name != project.name:
        raise HTTPException(status_code=400, detail="Project name confirmation does not match")

    nas_moved_to = None
    if project.ayon_project_name:
        nas_moved_to = ayon_service.trash_move_client_delivery(project.ayon_project_name)

    counts = PurgeCounts()
    _purge_project(db, project_id, counts)
    db.commit()

    return ProjectPurgeNowResponse(status="purged", counts=asdict(counts), nas_moved_to=nas_moved_to)


# ── Ayon project sync ────────────────────────────────────────────────────────────
# Live browse only: nothing from Ayon is mirrored into FreeFrame's DB except the
# ayon_project_name link recorded on activation, so this list is always exactly
# what Ayon currently has (see services/ayon_service.py).

@router.get("/ayon/projects", response_model=list[AyonProjectSummary])
def list_ayon_projects(db: Session = Depends(get_db), current_user: User = Depends(require_staff_or_admin)):
    """All Ayon projects, flagged with whether they're already linked to a FreeFrame project."""
    ayon_projects = ayon_service.list_projects()

    linked = {
        p.ayon_project_name: p.id
        for p in db.query(Project).filter(Project.ayon_project_name.isnot(None), Project.deleted_at.is_(None)).all()
    }

    return [
        AyonProjectSummary(
            name=p["name"],
            code=p.get("code", ""),
            active=p.get("active", True),
            linked=p["name"] in linked,
            freeframe_project_id=linked.get(p["name"]),
        )
        for p in ayon_projects
    ]


@router.post("/ayon/projects/{ayon_project_name}/activate", response_model=ProjectResponse)
def activate_ayon_project(
    ayon_project_name: str,
    body: ActivateAyonProjectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Create (or return, if already activated) the FreeFrame project linked to an Ayon project."""
    existing = db.query(Project).filter(
        Project.ayon_project_name == ayon_project_name, Project.deleted_at.is_(None)
    ).first()
    if existing:
        return ProjectResponse.model_validate(existing)

    # Confirm the Ayon project actually exists before creating anything for it.
    # active_only=False: an admin naming a project directly (vs. picking from
    # the /ayon/projects list) should still be able to activate an inactive one.
    ayon_projects = {p["name"] for p in ayon_service.list_projects(active_only=False)}
    if ayon_project_name not in ayon_projects:
        raise HTTPException(status_code=404, detail=f"Ayon project '{ayon_project_name}' not found")

    # A previously-linked project can end up soft-deleted (via the regular
    # DELETE /projects/{id} flow) without going through Deactivate above, which
    # would have cleared ayon_project_name. That leftover row still holds the
    # value ayon_project_name is uniquely constrained on, so re-activating
    # must reuse/undelete it rather than inserting a duplicate (which would
    # violate uq_projects_ayon_project_name and 500).
    stale = db.query(Project).filter(
        Project.ayon_project_name == ayon_project_name, Project.deleted_at.is_not(None)
    ).first()
    if stale:
        stale.deleted_at = None
        db.commit()
        db.refresh(stale)
        return ProjectResponse.model_validate(stale)

    project = Project(
        name=body.freeframe_project_name or ayon_project_name,
        created_by=current_user.id,
        ayon_project_name=ayon_project_name,
    )
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=current_user.id, role=ProjectRole.owner))
    db.commit()
    db.refresh(project)
    return ProjectResponse.model_validate(project)


@router.post("/ayon/projects/{ayon_project_name}/deactivate", response_model=ProjectResponse)
def deactivate_ayon_project(
    ayon_project_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Unlinks the FreeFrame project from Ayon (clears ayon_project_name) so
    the Ayon Client Delivery Watcher / Comment Relay stop touching it, AND
    soft-deletes the FreeFrame project itself (same mechanism as
    DELETE /projects/{id}) so it also disappears from the regular Projects
    list, matching what "deactivate" actually implies - not just a dangling
    unlinked project still showing up everywhere. Nothing is hard-deleted:
    assets/comments/members are all retained under the existing soft-delete
    retention window (see tasks/cleanup_tasks.py), and clearing
    ayon_project_name also frees the name up for a future re-activation."""
    project = db.query(Project).filter(
        Project.ayon_project_name == ayon_project_name, Project.deleted_at.is_(None)
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"No FreeFrame project is linked to Ayon project '{ayon_project_name}'")
    project.ayon_project_name = None
    project.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)
    return ProjectResponse.model_validate(project)


# ── Ayon connection: Settings > Admin > Ayon Projects ───────────────────────
# Optional DB-backed override for the Pinokio launcher's AYON_URL/AYON_API_KEY
# env config (see services/ayon_service.py._resolve_credentials) - lets an
# admin repoint or rotate the connection without restarting the launcher.

def _mask_ayon_key(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 4:
        return "*" * len(key)
    return "*" * (len(key) - 4) + key[-4:]


@router.get("/ayon/connection", response_model=AyonConnectionResponse)
def get_ayon_connection(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    row = db.query(InstanceSettings).first()
    db_url = row.ayon_url if row else None
    db_key = row.ayon_api_key if row else None
    url = db_url or settings.ayon_url
    api_key = db_key or settings.ayon_api_key
    source = "database" if (db_url or db_key) else ("launcher" if (url or api_key) else "unset")
    return AyonConnectionResponse(ayon_url=url, api_key_masked=_mask_ayon_key(api_key), source=source)


@router.put("/ayon/connection", response_model=AyonConnectionResponse)
def update_ayon_connection(
    body: AyonConnectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    row = get_or_create_instance_settings(db)
    if body.ayon_url is not None:
        row.ayon_url = body.ayon_url.strip() or None
    if body.ayon_api_key is not None:
        row.ayon_api_key = body.ayon_api_key.strip() or None
    db.commit()
    db.refresh(row)
    # Drop the cached ayon_api SDK connection so the new credentials take
    # effect on the very next Ayon call instead of waiting for a credential
    # mismatch to be noticed (which never happens if only one field changed
    # in a way that still differs, but is a cheap no-op otherwise).
    ayon_service.reset_connection()

    url = row.ayon_url or settings.ayon_url
    api_key = row.ayon_api_key or settings.ayon_api_key
    source = "database" if (row.ayon_url or row.ayon_api_key) else ("launcher" if (url or api_key) else "unset")
    return AyonConnectionResponse(ayon_url=url, api_key_masked=_mask_ayon_key(api_key), source=source)


# ── Email config: Settings > Admin > Email ──────────────────────────────────

@router.get("/email/status", response_model=EmailStatusResponse)
def get_email_status(current_user: User = Depends(require_admin)):
    """Current mail provider config, no secrets - powers the status card on
    Settings > Admin > Email."""
    resp = EmailStatusResponse(
        provider=settings.mail_provider,
        configured=mail_is_configured(),
        from_address=settings.mail_from_address,
        from_name=settings.mail_from_name,
    )
    if settings.mail_provider == "smtp":
        resp.smtp_host = settings.smtp_host
        resp.smtp_port = settings.smtp_port
        resp.smtp_use_tls = settings.smtp_use_tls
    return resp


@router.post("/email/test")
def send_test_email(body: SendTestEmailRequest, current_user: User = Depends(require_admin)):
    """Sends one real test email synchronously (not via Celery) so the admin
    gets an immediate pass/fail instead of a fire-and-forget queue send that
    silently retries on failure."""
    success = email_service.send_email(
        body.to_email,
        "FreeFrame test email",
        "<p>This is a test email from FreeFrame's Settings &gt; Admin &gt; Email page.</p>"
        "<p>If you received this, your mail configuration is working.</p>",
        "This is a test email from FreeFrame's Settings > Admin > Email page. "
        "If you received this, your mail configuration is working.",
    )
    if not success:
        raise HTTPException(
            status_code=502,
            detail="Send failed - check the mail provider credentials and server logs for the underlying error.",
        )


# ── Share Links: Settings > Admin > Share Links ─────────────────────────────
# Instance-wide oversight - every share link across every project, so an admin
# can spot and cancel one without having to be a member of that project (see
# routers/share.py's DELETE /share/{token}, which already superadmin-bypasses
# require_project_role).

@router.get("/share-links", response_model=list[AdminShareLinkItem])
def list_all_share_links(current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from ..models.share import ShareLink
    from ..models.asset import Asset
    from ..models.folder import Folder
    from ..services.permissions import is_staff_user

    links = (
        db.query(ShareLink)
        .filter(ShareLink.deleted_at.is_(None))
        .order_by(ShareLink.created_at.desc())
        .all()
    )
    if not links:
        return []

    creator_ids = {l.created_by for l in links}
    creators = {u.id: u for u in db.query(User).filter(User.id.in_(creator_ids)).all()}

    asset_ids = {l.asset_id for l in links if l.asset_id}
    folder_ids = {l.folder_id for l in links if l.folder_id}
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(asset_ids)).all()} if asset_ids else {}
    folders = {f.id: f for f in db.query(Folder).filter(Folder.id.in_(folder_ids)).all()} if folder_ids else {}

    project_ids = set()
    for l in links:
        if l.project_id:
            project_ids.add(l.project_id)
        elif l.asset_id and l.asset_id in assets:
            project_ids.add(assets[l.asset_id].project_id)
        elif l.folder_id and l.folder_id in folders:
            project_ids.add(folders[l.folder_id].project_id)
    projects = {p.id: p for p in db.query(Project).filter(Project.id.in_(project_ids)).all()} if project_ids else {}

    result: list[AdminShareLinkItem] = []
    for l in links:
        if l.asset_id and l.asset_id in assets:
            share_type, project_id = "asset", assets[l.asset_id].project_id
        elif l.folder_id and l.folder_id in folders:
            share_type, project_id = "folder", folders[l.folder_id].project_id
        elif l.project_id:
            share_type, project_id = "project", l.project_id
        else:
            continue  # dangling link (target deleted out from under it) - not shown
        project = projects.get(project_id)
        creator = creators.get(l.created_by)
        result.append(AdminShareLinkItem(
            id=l.id,
            token=l.token,
            title=l.title,
            share_type=share_type,
            project_id=project_id,
            project_name=project.name if project else "(deleted project)",
            created_by_name=creator.name if creator else "(deleted user)",
            created_by_email=creator.email if creator else "",
            is_client=(not is_staff_user(db, creator)) if creator and not creator.is_superadmin else False,
            is_enabled=l.is_enabled,
            visibility=l.visibility,
            permission=l.permission.value if hasattr(l.permission, "value") else l.permission,
            allow_download=l.allow_download,
            show_watermark=l.show_watermark,
            expires_at=l.expires_at.isoformat() if l.expires_at else None,
            created_at=l.created_at.isoformat(),
        ))
    return result
    return {"status": "sent", "to": body.to_email}
