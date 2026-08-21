from fastapi import APIRouter, Depends, HTTPException, status, Query, Response, File, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.user import User
from ..models.asset import Asset, AssetVersion, MediaFile, AssetType, FileType, ProcessingStatus
from ..models.project import Project, ProjectMember, ProjectRole
from ..models.share import AssetShare
from ..models.activity import Mention, Notification, NotificationType
from ..schemas.asset import AssetResponse, AssetVersionResponse, AssetUpdate, StreamUrlResponse, MediaFileResponse
from ..schemas.notification import AssignmentUpdate
from ..services.permissions import require_project_role, require_asset_access, can_access_asset, is_public_project, get_project_member
from ..services.s3_service import generate_presigned_get_url, build_download_filename
from .hls_proxy import create_hls_token
from ..schemas.upload import InitiateUploadRequest, InitiateUploadResponse, ALLOWED_MIME_TYPES, mime_to_asset_type
from ..services.storage import upload_guard_error
from ..services.s3_service import create_multipart_upload, put_object, delete_object
from .projects import ALLOWED_POSTER_TYPES, MAX_POSTER_SIZE

router = APIRouter(tags=["assets"])


def _build_asset_response(asset: Asset, db: Session) -> AssetResponse:
    """Build AssetResponse with latest version and its files."""
    latest_version = db.query(AssetVersion).filter(
        AssetVersion.asset_id == asset.id,
        AssetVersion.deleted_at.is_(None),
    ).order_by(AssetVersion.version_number.desc()).first()

    version_response = None
    thumbnail_url = None
    display_name = None
    if latest_version:
        files = db.query(MediaFile).filter(MediaFile.version_id == latest_version.id).all()
        version_response = AssetVersionResponse.model_validate(latest_version)
        version_response.files = [MediaFileResponse.model_validate(f) for f in files]
        # Get thumbnail from first file that has one.
        # Audio stores waveform JSON in s3_key_thumbnail — skip it, it's not an image.
        if asset.asset_type != AssetType.audio:
            for f in files:
                if f.s3_key_thumbnail:
                    thumbnail_url = generate_presigned_get_url(f.s3_key_thumbnail)
                    break
        # Show the exact filename the shown version was delivered under
        # (e.g. matching the NAS's own naming - "zd_111_reviewAnimation_v002_h264.mp4")
        # rather than Asset.name, which is only ever set once at creation and
        # can't correctly represent every version if they arrived under
        # different filenames. Needed so a comment on this asset can be
        # traced back to the right original delivered file when relayed to
        # Ayon (see ayon_relay.py).
        if files and files[0].original_filename:
            display_name = files[0].original_filename

    resp = AssetResponse.model_validate(asset)
    if display_name:
        resp.name = display_name
    resp.latest_version = version_response
    resp.thumbnail_url = thumbnail_url
    return resp


def _build_asset_responses_bulk(assets: list[Asset], db: Session, folder_scope: uuid.UUID | None = None) -> list[AssetResponse]:
    """Build AssetResponse list with bulk-loaded versions and files (no N+1).

    folder_scope: when browsing one specific folder (list_assets's folder_id
    filter), the "latest version" shown for each asset is the highest
    version actually FILED UNDER THAT FOLDER (AssetVersion.folder_id) rather
    than the asset's true highest version overall. An asset delivered across
    several date-folders (see AssetVersion.folder_id on the model) otherwise
    always shows its globally-latest version even inside an older date's
    folder, which reads as "wrong" content for that folder (e.g. an Aug 20
    folder that only ever received v001-v002 showing v003, delivered on Aug
    21, because it happens to be the same underlying asset).
    """
    if not assets:
        return []

    asset_ids = [a.id for a in assets]

    def _latest_per_asset(ids: list[uuid.UUID], scope: uuid.UUID | None) -> list[AssetVersion]:
        q = db.query(
            AssetVersion.asset_id,
            func.max(AssetVersion.version_number).label("max_version"),
        ).filter(AssetVersion.asset_id.in_(ids), AssetVersion.deleted_at.is_(None))
        if scope is not None:
            q = q.filter(AssetVersion.folder_id == scope)
        subq = q.group_by(AssetVersion.asset_id).subquery()
        return (
            db.query(AssetVersion)
            .join(subq, (AssetVersion.asset_id == subq.c.asset_id) & (AssetVersion.version_number == subq.c.max_version))
            .all()
        )

    version_by_asset = {v.asset_id: v for v in _latest_per_asset(asset_ids, folder_scope)}

    # folder_scope can leave some assets with no match at all: an asset
    # matched into this folder via its own (legacy) Asset.folder_id, whose
    # versions predate AssetVersion.folder_id and are therefore all NULL,
    # has nothing satisfying `folder_id == scope`. Fall back to those
    # assets' true global latest version rather than showing them with no
    # version/thumbnail at all.
    missing_ids = [aid for aid in asset_ids if aid not in version_by_asset]
    if missing_ids and folder_scope is not None:
        version_by_asset.update({v.asset_id: v for v in _latest_per_asset(missing_ids, None)})

    # Bulk load media files for all those versions
    version_ids = [v.id for v in version_by_asset.values()]
    all_files = db.query(MediaFile).filter(MediaFile.version_id.in_(version_ids)).all() if version_ids else []
    files_by_version: dict = {}
    for f in all_files:
        files_by_version.setdefault(f.version_id, []).append(f)

    result = []
    for asset in assets:
        version = version_by_asset.get(asset.id)
        version_response = None
        thumbnail_url = None
        display_name = None
        if version:
            files = files_by_version.get(version.id, [])
            version_response = AssetVersionResponse.model_validate(version)
            version_response.files = [MediaFileResponse.model_validate(f) for f in files]
            # Audio stores waveform JSON in s3_key_thumbnail — skip it, it's not an image.
            if asset.asset_type != AssetType.audio:
                for f in files:
                    if f.s3_key_thumbnail:
                        thumbnail_url = generate_presigned_get_url(f.s3_key_thumbnail)
                        break
            # Show the exact filename the shown (possibly folder_scope'd)
            # version was delivered under - see _build_asset_response above.
            if files and files[0].original_filename:
                display_name = files[0].original_filename

        asset_resp = AssetResponse.model_validate(asset)
        if display_name:
            asset_resp.name = display_name
        asset_resp.latest_version = version_response
        asset_resp.thumbnail_url = thumbnail_url
        result.append(asset_resp)
    return result


@router.get("/projects/{project_id}/assets", response_model=list[AssetResponse])
def list_assets(
    project_id: uuid.UUID,
    include_failed: bool = Query(False, description="Include assets whose latest version failed processing"),
    folder_id: Optional[str] = Query(None, description="Filter by folder. 'root' for root level, UUID for specific folder."),
    ayon_task_id: Optional[str] = Query(None, description="Filter by linked Ayon task id (scripts/ayon_client_watcher.py uses this to find an existing asset to attach a new version to, instead of creating a duplicate)."),
    ayon_folder_id: Optional[str] = Query(None, description="Filter by linked Ayon folder id - same purpose as ayon_task_id, for deliveries with no task match."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Allow access if user is a project member OR the project is public
    member = get_project_member(db, project_id, current_user.id)
    if not member and not is_public_project(db, project_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a project member")

    query = db.query(Asset).filter(
        Asset.project_id == project_id,
        Asset.deleted_at.is_(None),
    )

    folder_scope: Optional[uuid.UUID] = None
    if folder_id == "root":
        query = query.filter(Asset.folder_id.is_(None))
    elif folder_id is not None:
        folder_scope = uuid.UUID(folder_id)
        # An asset belongs here if its own (primary) folder_id matches -
        # true for every asset, old or new - OR if any of its versions were
        # individually filed here (AssetVersion.folder_id, only populated
        # for versions created after that column existed - see the model).
        # The latter is what surfaces an asset inside an *older* date-folder
        # its newest version has since moved past, e.g.
        # ayon_client_watcher.py delivering v001-v002 under 2026-08-20 and a
        # later v003 under 2026-08-21 for the same asset.
        versioned_here = db.query(AssetVersion.asset_id).filter(
            AssetVersion.folder_id == folder_scope, AssetVersion.deleted_at.is_(None)
        ).distinct()
        query = query.filter(or_(Asset.folder_id == folder_scope, Asset.id.in_(versioned_here)))
    if ayon_task_id is not None:
        query = query.filter(Asset.ayon_task_id == ayon_task_id)
    if ayon_folder_id is not None:
        query = query.filter(Asset.ayon_folder_id == ayon_folder_id)

    assets = query.all()

    if not include_failed:
        # Exclude assets where the only version is failed or still uploading
        asset_ids = [a.id for a in assets]
        if asset_ids:
            # Find assets that have at least one non-failed, non-uploading version
            usable = set(
                row[0] for row in db.query(AssetVersion.asset_id).filter(
                    AssetVersion.asset_id.in_(asset_ids),
                    AssetVersion.deleted_at.is_(None),
                    AssetVersion.processing_status.notin_([ProcessingStatus.failed, ProcessingStatus.uploading]),
                ).distinct().all()
            )
            # Also include assets with no versions yet (just created)
            has_any_version = set(
                row[0] for row in db.query(AssetVersion.asset_id).filter(
                    AssetVersion.asset_id.in_(asset_ids),
                    AssetVersion.deleted_at.is_(None),
                ).distinct().all()
            )
            assets = [a for a in assets if a.id in usable or a.id not in has_any_version]

    return _build_asset_responses_bulk(assets, db, folder_scope=folder_scope)


@router.get("/assets/{asset_id}", response_model=AssetResponse)
def get_asset(
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    require_asset_access(db, asset, current_user)
    return _build_asset_response(asset, db)


@router.patch("/assets/{asset_id}", response_model=AssetResponse)
def update_asset(
    asset_id: uuid.UUID,
    body: AssetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    require_project_role(db, asset.project_id, current_user, ProjectRole.editor)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(asset, field, value)
    db.commit()
    db.refresh(asset)
    return _build_asset_response(asset, db)


@router.post("/assets/{asset_id}/versions/{version_id}/thumbnail", response_model=AssetResponse)
async def set_version_thumbnail(
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Overrides one version's thumbnail with a caller-supplied image - e.g.
    scripts/ayon_client_watcher.py uses this to hand off a studio-delivered
    *_thumbnail.jpg instead of leaving the auto-extracted video frame.
    Always wins regardless of call order relative to the async transcode
    job: tasks/transcode_tasks.py._process_video only fills s3_key_thumbnail
    when it's still empty, so it never clobbers a value set here."""
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    require_project_role(db, asset.project_id, current_user, ProjectRole.editor)

    media_file = db.query(MediaFile).filter(MediaFile.version_id == version_id).first()
    if not media_file:
        raise HTTPException(status_code=404, detail="Version not found")

    if file.content_type not in ALLOWED_POSTER_TYPES:
        raise HTTPException(status_code=400, detail="File must be JPEG, PNG, WebP, or GIF")
    data = await file.read()
    if len(data) > MAX_POSTER_SIZE:
        raise HTTPException(status_code=400, detail="File must be under 10MB")

    if media_file.s3_key_thumbnail:
        try:
            delete_object(media_file.s3_key_thumbnail)
        except Exception:
            pass

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "jpg"
    s3_key = f"thumbnails/{asset.project_id}/{asset_id}/{version_id}.{ext}"
    put_object(s3_key, data, content_type=file.content_type, cache_control="max-age=86400")
    media_file.s3_key_thumbnail = s3_key
    db.commit()

    return _build_asset_response(asset, db)


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    require_project_role(db, asset.project_id, current_user, ProjectRole.editor)
    asset.deleted_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/assets/{asset_id}/versions", response_model=list[AssetVersionResponse])
def list_asset_versions(
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    require_asset_access(db, asset, current_user)

    versions = db.query(AssetVersion).filter(
        AssetVersion.asset_id == asset_id,
        AssetVersion.deleted_at.is_(None),
    ).order_by(AssetVersion.version_number.desc()).all()

    result = []
    version_ids = [v.id for v in versions]
    all_files = db.query(MediaFile).filter(MediaFile.version_id.in_(version_ids)).all() if version_ids else []
    files_by_version: dict = {}
    for f in all_files:
        files_by_version.setdefault(f.version_id, []).append(f)

    for v in versions:
        vr = AssetVersionResponse.model_validate(v)
        vr.files = [MediaFileResponse.model_validate(f) for f in files_by_version.get(v.id, [])]
        result.append(vr)
    return result


@router.get("/assets/{asset_id}/stream", response_model=StreamUrlResponse)
def get_stream_url(
    asset_id: uuid.UUID,
    version_id: Optional[uuid.UUID] = Query(default=None),
    download: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    require_asset_access(db, asset, current_user)

    # Get the requested version or latest
    if version_id:
        version = db.query(AssetVersion).filter(
            AssetVersion.id == version_id,
            AssetVersion.asset_id == asset_id,
            AssetVersion.deleted_at.is_(None),
        ).first()
    else:
        version = db.query(AssetVersion).filter(
            AssetVersion.asset_id == asset_id,
            AssetVersion.deleted_at.is_(None),
        ).order_by(AssetVersion.version_number.desc()).first()

    if not version:
        raise HTTPException(status_code=404, detail="No version found")
    if version.processing_status != ProcessingStatus.ready:
        raise HTTPException(status_code=409, detail="Asset version is not ready yet")

    media_file = db.query(MediaFile).filter(MediaFile.version_id == version.id).first()
    if not media_file:
        raise HTTPException(status_code=404, detail="Media file not found")

    if asset.asset_type == AssetType.video and media_file.s3_key_processed:
        if download:
            # For video downloads, use the raw file (original upload) so user gets a single file
            s3_key = media_file.s3_key_raw or media_file.s3_key_processed
            filename = build_download_filename(asset.name, media_file.original_filename or s3_key)
            url = generate_presigned_get_url(s3_key, download_filename=filename)
        else:
            # Route through the HLS proxy so the master playlist, variant
            # playlists, and .ts segments all get served via short-lived
            # presigned URLs — the S3 bucket can stay fully private. (#51)
            token = create_hls_token(media_file.s3_key_processed)
            url = f"/stream/hls/master.m3u8?token={token}"
    else:
        s3_key = media_file.s3_key_processed or media_file.s3_key_raw
        if download:
            filename = build_download_filename(asset.name, media_file.original_filename or s3_key)
            url = generate_presigned_get_url(s3_key, download_filename=filename)
        else:
            url = generate_presigned_get_url(s3_key)

    return StreamUrlResponse(url=url, asset_type=asset.asset_type)


@router.get("/assets/{asset_id}/versions/{version_id}/frame")
def get_frame_at_time(
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    t: float = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Extracts a single JPEG frame from the version's original (raw) file at
    time `t` seconds. Works for images too (ffmpeg treats a static image as a
    1-frame input, so `t` is simply ignored for those).

    Used by the Ayon Comment Relay (scripts/ayon_relay.py) to composite a
    drawing annotation over the actual burned-in video frame it was drawn on
    top of, instead of relaying just the isolated pencil strokes on a blank
    canvas - see annotation_render.py's render_annotation_png, which only
    ever rendered the drawing layer.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    require_asset_access(db, asset, current_user)

    version = db.query(AssetVersion).filter(
        AssetVersion.id == version_id,
        AssetVersion.asset_id == asset_id,
        AssetVersion.deleted_at.is_(None),
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    media_file = db.query(MediaFile).filter(MediaFile.version_id == version.id).first()
    if not media_file or not media_file.s3_key_raw:
        raise HTTPException(status_code=404, detail="Media file not found")

    input_url = generate_presigned_get_url(media_file.s3_key_raw)

    def _extract(seek: float, out_path: Path) -> subprocess.CompletedProcess:
        # -ss AFTER -i (output/frame-accurate seeking), not before: pre-input
        # seeking can overshoot past EOF on very short clips (some comments
        # here are on sub-1-second test deliveries) and silently produce zero
        # frames even though the timestamp is technically in-range. Slower
        # for long footage, but this only ever decodes up to `seek`, so it's
        # still fine for a single frame grab.
        cmd = [
            "ffmpeg", "-y", "-i", input_url, "-ss", str(seek),
            "-pix_fmt", "yuvj420p", "-q:v", "2", "-frames:v", "1",
            str(out_path),
        ]
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=60)

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir) / "frame.jpg"
        result = _extract(t, out_path)
        if (result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0) and t > 0:
            # Timestamp landed at/past the last frame (e.g. an ultra-short
            # clip) - retry from the very start rather than failing outright.
            result = _extract(0, out_path)
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            raise HTTPException(
                status_code=502,
                detail=f"Frame extraction failed: {(result.stderr or '').strip()[-500:] or 'no ffmpeg output'}",
            )
        return Response(content=out_path.read_bytes(), media_type="image/jpeg")


@router.post("/assets/{asset_id}/versions", response_model=InitiateUploadResponse)
def initiate_new_version(
    asset_id: uuid.UUID,
    body: InitiateUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Initiate upload of a new version for an existing asset."""
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    require_project_role(db, asset.project_id, current_user, ProjectRole.editor)

    if body.mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    guard_error = upload_guard_error(db, body.file_size_bytes)
    if guard_error:
        raise HTTPException(status_code=400, detail=guard_error)

    last_version = db.query(AssetVersion).filter(
        AssetVersion.asset_id == asset_id,
        AssetVersion.deleted_at.is_(None),
    ).order_by(AssetVersion.version_number.desc()).first()
    next_version_number = (last_version.version_number + 1) if last_version else 1

    version = AssetVersion(
        asset_id=asset_id,
        version_number=next_version_number,
        processing_status=ProcessingStatus.uploading,
        created_by=current_user.id,
    )
    db.add(version)
    db.flush()

    ext = os.path.splitext(body.original_filename)[1].lower()
    s3_key = f"raw/{asset.project_id}/{asset_id}/{version.id}/original{ext}"
    upload_id = create_multipart_upload(s3_key, body.mime_type)

    file_type_map = {AssetType.image: FileType.image, AssetType.audio: FileType.audio, AssetType.video: FileType.video, AssetType.image_carousel: FileType.image}
    media_file = MediaFile(
        version_id=version.id,
        file_type=file_type_map.get(asset.asset_type, FileType.video),
        original_filename=body.original_filename,
        mime_type=body.mime_type,
        file_size_bytes=body.file_size_bytes,
        s3_key_raw=s3_key,
    )
    db.add(media_file)
    db.commit()

    return InitiateUploadResponse(
        upload_id=upload_id,
        s3_key=s3_key,
        asset_id=asset_id,
        version_id=version.id,
    )


@router.patch("/assets/{asset_id}/assignment", response_model=AssetResponse)
def update_assignment(
    asset_id: uuid.UUID,
    body: AssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    require_project_role(db, asset.project_id, current_user, ProjectRole.editor)

    if "assignee_id" in body.model_fields_set:
        asset.assignee_id = body.assignee_id
    if "due_date" in body.model_fields_set:
        asset.due_date = body.due_date

    if "assignee_id" in body.model_fields_set and body.assignee_id is not None:
        notification = Notification(
            user_id=body.assignee_id,
            type=NotificationType.assignment,
            asset_id=asset.id,
        )
        db.add(notification)

    db.commit()
    db.refresh(asset)
    return _build_asset_response(asset, db)


@router.get("/assets/{asset_id}/assignment")
def get_assignment(
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    require_project_role(db, asset.project_id, current_user, ProjectRole.viewer)
    return {
        "assignee_id": str(asset.assignee_id) if asset.assignee_id else None,
        "due_date": asset.due_date.isoformat() if asset.due_date else None,
    }
