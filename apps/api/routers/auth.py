from urllib.parse import urlencode
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_auth_requests
from sqlalchemy.orm import Session
import uuid
import secrets
from datetime import datetime, timedelta, timezone
from ..config import settings
from ..database import get_db
from ..schemas.auth import (
    LoginRequest, TokenResponse,
    RefreshRequest, UserResponse, InviteRequest,
    SendMagicCodeRequest, SendMagicCodeResponse,
    VerifyMagicCodeRequest, SetPasswordRequest,
    AcceptInviteRequest, InviteInfoResponse,
    ChangePasswordRequest,
)
from ..services.auth_service import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_user_by_email, get_user_by_id,
)
from ..services.redis_service import (
    generate_magic_code, store_magic_code, verify_magic_code as redis_verify_magic_code,
    MAGIC_CODE_EXPIRY_SECONDS, store_oauth_state, consume_oauth_state,
)
from ..tasks.email_tasks import send_magic_code_email, send_invite_email
from ..tasks.celery_app import send_task_safe
from ..models.user import User, UserStatus
from ..middleware.auth import get_current_user
from ..middleware.rate_limit import rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

MAGIC_CODE_EXPIRY_MINUTES = MAGIC_CODE_EXPIRY_SECONDS // 60


def _generate_invite_token() -> str:
    """Generate a secure invite token."""
    return secrets.token_urlsafe(48)


@router.post("/send-magic-code", response_model=SendMagicCodeResponse, dependencies=[Depends(rate_limit("send_magic_code", 5, 600))])
def send_magic_code(body: SendMagicCodeRequest, db: Session = Depends(get_db)):
    """
    Send magic code to an existing user's email, for login.

    Does not create accounts: only an admin invite (/users/invite) or
    /setup/create-superadmin may provision a new user. An unrecognized email
    gets the same response as a known one, so this endpoint can't be used to
    enumerate registered emails.
    """
    user = get_user_by_email(db, body.email)

    if not user:
        return SendMagicCodeResponse(
            message="Magic code sent to your email",
            email=body.email,
        )

    # Generate and store magic code in Redis
    code = generate_magic_code()
    store_magic_code(body.email, code)

    # Queue email via Celery (async)
    try:
        send_task_safe(send_magic_code_email, body.email, code, MAGIC_CODE_EXPIRY_MINUTES)
    except Exception:
        pass  # Email delivery is best-effort; code is already in Redis
    
    return SendMagicCodeResponse(
        message="Magic code sent to your email",
        email=body.email,
    )


@router.post("/verify-magic-code", response_model=TokenResponse, dependencies=[Depends(rate_limit("verify_magic_code", 10, 600))])
def verify_magic_code(body: VerifyMagicCodeRequest, db: Session = Depends(get_db)):
    """
    Verify magic code and return tokens.
    Returns needs_password=True if user hasn't set a password yet.
    """
    user = get_user_by_email(db, body.email)
    
    # "No such user" and "deactivated" get the same generic failure as a wrong/expired code —
    # distinguishing them would let a caller enumerate registered or deactivated emails.
    if not user or user.status == UserStatus.deactivated:
        raise HTTPException(status_code=401, detail="Invalid or expired code")

    # Verify magic code from Redis
    success, error = redis_verify_magic_code(body.email, body.code)
    if not success:
        raise HTTPException(status_code=401, detail=error)
    
    # Mark email as verified
    user.email_verified = True
    
    # If user was pending verification, activate them
    if user.status == UserStatus.pending_verification:
        user.status = UserStatus.active

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    
    # Check if user needs to set password
    needs_password = user.password_hash is None
    
    return TokenResponse(
        access_token=create_access_token(str(user.id), token_version=user.token_version),
        refresh_token=create_refresh_token(str(user.id), token_version=user.token_version),
        needs_password=needs_password,
    )


@router.post("/set-password", response_model=UserResponse)
def set_password(
    body: SetPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set password for authenticated user (after magic code verification, or
    to clear an admin-created account's forced must_change_password)."""
    current_user.password_hash = hash_password(body.password)
    current_user.must_change_password = False
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/invite/{token}", response_model=InviteInfoResponse)
def get_invite_info(token: str, db: Session = Depends(get_db)):
    """Get info about an invite token (for the set-password screen)."""
    user = db.query(User).filter(
        User.invite_token == token,
        User.deleted_at.is_(None),
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Invalid invite link")
    
    if user.invite_token_expires_at and user.invite_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invite link expired")
    
    return InviteInfoResponse(
        email=user.email,
        name=user.name,
    )


@router.post("/accept-invite", response_model=TokenResponse)
def accept_invite(body: AcceptInviteRequest, db: Session = Depends(get_db)):
    """Accept invite and set password. Email is already verified via invite."""
    user = db.query(User).filter(
        User.invite_token == body.token,
        User.deleted_at.is_(None),
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Invalid invite link")
    
    if user.invite_token_expires_at and user.invite_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invite link expired")
    
    # Set password and activate user
    user.password_hash = hash_password(body.password)
    user.email_verified = True  # Invited users are pre-verified
    user.status = UserStatus.active
    user.invite_token = None
    user.invite_token_expires_at = None
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    return TokenResponse(
        access_token=create_access_token(str(user.id), token_version=user.token_version),
        refresh_token=create_refresh_token(str(user.id), token_version=user.token_version),
        needs_password=False,
    )


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("login", 10, 600))])
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Login with email + password."""
    user = get_user_by_email(db, body.email)
    if (
        not user
        or not user.password_hash
        or not verify_password(body.password, user.password_hash)
        or user.status == UserStatus.deactivated
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return TokenResponse(
        access_token=create_access_token(str(user.id), token_version=user.token_version),
        refresh_token=create_refresh_token(str(user.id), token_version=user.token_version),
        # Admin-created accounts (POST /admin/users) start flagged - the
        # password already works (it's a real login), but the frontend
        # routes this the same as a first-login magic-code user: straight to
        # the set-new-password screen before landing in the app.
        needs_password=user.must_change_password,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = get_user_by_id(db, uuid.UUID(payload["sub"]))
    if not user or user.status == UserStatus.deactivated:
        raise HTTPException(status_code=401, detail="User not found")
    if payload.get("ver", 1) != user.token_version:
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    return TokenResponse(
        access_token=create_access_token(str(user.id), token_version=user.token_version),
        refresh_token=create_refresh_token(str(user.id), token_version=user.token_version),
        needs_password=user.password_hash is None or user.must_change_password,
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me/preferences", response_model=UserResponse)
def update_preferences(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update user preferences (theme, etc). Merges with existing preferences."""
    current_prefs = current_user.preferences or {}
    current_prefs.update(body)
    current_user.preferences = current_prefs
    # Force SQLAlchemy to detect the JSON change
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(current_user, "preferences")
    db.commit()
    db.refresh(current_user)
    return current_user

def _require_google_configured() -> None:
    if not (settings.google_client_id and settings.google_client_secret and settings.google_oauth_redirect_uri):
        raise HTTPException(status_code=400, detail="Google login is not configured")


@router.get("/google/login")
def google_login():
    """Redirect to Google's consent screen. state is one-time, stored in
    Redis (see services/redis_service.py) rather than a session cookie -
    this app is otherwise entirely stateless-JWT."""
    _require_google_configured()
    state = secrets.token_urlsafe(32)
    store_oauth_state(state)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return RedirectResponse(f"{GOOGLE_AUTHORIZATION_URL}?{urlencode(params)}")


@router.get("/google/callback")
async def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    """Exchange the authorization code, verify the id_token's signature against
    Google's own rotating public keys (google-auth handles JWKS fetch/cache/
    rotation + audience/issuer checks), find-or-create the User by email, then
    hand back the same TokenResponse shape every other login path issues -
    see services/auth_service.py's create_access_token/create_refresh_token.
    Tokens travel back to the frontend in the URL *fragment* (not a query
    string), so they're never sent to any server or logged - only readable
    client-side by the callback page's own JS.
    """
    _require_google_configured()
    if not consume_oauth_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Google sign-in failed")
    id_token_str = token_resp.json().get("id_token")
    if not id_token_str:
        raise HTTPException(status_code=401, detail="Google sign-in failed")

    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str, google_auth_requests.Request(), settings.google_client_id,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    email = claims.get("email")
    if not email or not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="Google account has no verified email")
    google_id = claims["sub"]

    user = db.query(User).filter(User.google_id == google_id, User.deleted_at.is_(None)).first()
    if not user:
        # Not yet linked by google_id - fall back to matching by email so an
        # existing magic-code/password account gets linked instead of a
        # duplicate created (matches this email's account either way).
        user = get_user_by_email(db, email)
        if user:
            user.google_id = google_id
        else:
            user = User(
                email=email,
                name=claims.get("name") or email,
                avatar_url=claims.get("picture"),
                google_id=google_id,
                status=UserStatus.active,
                email_verified=True,
            )
            db.add(user)

    if user.status == UserStatus.deactivated:
        raise HTTPException(status_code=401, detail="This account has been deactivated")
    if user.status == UserStatus.pending_verification:
        user.status = UserStatus.active
    user.email_verified = True
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    # No needs_password gate here (unlike the magic-code/password flows): a
    # Google-authenticated account doesn't need a local password to sign in
    # again - it can always just use Google. Setting one is optional, done
    # later via Settings if they want a password-based fallback too.
    fragment = urlencode({
        "access_token": create_access_token(str(user.id), token_version=user.token_version),
        "refresh_token": create_refresh_token(str(user.id), token_version=user.token_version),
    })
    return RedirectResponse(f"{settings.frontend_url}/auth/google/callback#{fragment}")


@router.patch("/change-password", response_model=TokenResponse, status_code=status.HTTP_200_OK)
def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change password for authenticated user."""
    if current_user.password_hash is None:
        raise HTTPException(status_code=400, detail="No password set for this account; use set-password instead")
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.password_hash = hash_password(body.new_password)
    current_user.token_version += 1
    db.commit()
    db.refresh(current_user)
    return TokenResponse(
        access_token=create_access_token(str(current_user.id), token_version=current_user.token_version),
        refresh_token=create_refresh_token(str(current_user.id), token_version=current_user.token_version),
        needs_password=False,
    )
