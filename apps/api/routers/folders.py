import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.asset import Asset, AssetVersion, MediaFile
from ..models.folder import Folder
from ..models.project import Project, ProjectRole
from ..models.user import User
from ..schemas.folder import (
    AssetMoveRequest,
    BulkMoveRequest,
    FolderCreate,
    FolderResponse,
    FolderTreeNode,
    FolderUpdate,
)
from ..services.permissions import require_project_role, get_project_member, is_public_project

router = APIRouter(tags=["folders"])

MAX_FOLDER_DEPTH = 10


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _get_folder(db: Session, folder_id: uuid.UUID) -> Folder:
    folder = (
        db.query(Folder)
        .filter(Folder.id == folder_id, Folder.deleted_at.is_(None))
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder



def _folder_zip_basename(db: Session, folder: Folder, sanitize) -> str:
    """Only a version folder (e.g. "v003") gets the ancestor-chain name
    (folder_task_version, e.g. "111_Animation_v003") - that pattern only
    makes sense at the leaf where "version" is a real segment. Downloading
    any other folder (a task, a shot, a date, ...) zips everything under it
    recursively, so its own name alone is the meaningful one - dragging in
    ancestor names there just produces noise (e.g. the project's own name
    showing up in "z_dummyTest_2026-08-18_111.zip")."""
    if re.match(r"v\d+$", folder.name, re.IGNORECASE):
        name_parts = [folder.name]
        cursor = folder
        for _ in range(2):
            if not cursor.parent_id:
                break
            cursor = db.query(Folder).filter(Folder.id == cursor.parent_id).first()
            if not cursor:
                break
            name_parts.append(cursor.name)
        name_parts.reverse()
    else:
        name_parts = [folder.name]
    return "_".join(sanitize(p) for p in name_parts)


def _get_descendant_ids(db: Session, folder_id: uuid.UUID) -> list[uuid.UUID]:
    """Get all descendant folder IDs (BFS)."""
    descendants: list[uuid.UUID] = []
    queue = [folder_id]
    while queue:
        current = queue.pop(0)
        children = (
            db.query(Folder.id)
            .filter(Folder.parent_id == current, Folder.deleted_at.is_(None))
            .all()
        )
        for (child_id,) in children:
            descendants.append(child_id)
            queue.append(child_id)
    return descendants


def _get_depth(db: Session, folder_id: Optional[uuid.UUID]) -> int:
    """Count depth from root to folder_id."""
    depth = 0
    current_id = folder_id
    while current_id:
        depth += 1
        folder = db.query(Folder).filter(Folder.id == current_id).first()
        if not folder:
            break
        current_id = folder.parent_id
    return depth


def _asset_ids_in_folder(db: Session, folder_id: uuid.UUID):
    """Distinct asset ids that belong in this folder: either the asset's own
    (primary) folder_id - true for every asset, old or new - or any
    individual version filed here (AssetVersion.folder_id, only populated
    for versions created after that column existed). The latter is what
    makes an older date-folder still show the asset it received a version
    of, even after a newer version (filed elsewhere) became that asset's
    overall latest - see routers/assets.py list_assets's matching folder_scope
    logic."""
    own = db.query(Asset.id).filter(Asset.folder_id == folder_id, Asset.deleted_at.is_(None))
    via_version = db.query(AssetVersion.asset_id).filter(
        AssetVersion.folder_id == folder_id, AssetVersion.deleted_at.is_(None)
    )
    return {row[0] for row in own.union(via_version).all()}


def _compute_item_count(db: Session, folder_id: uuid.UUID) -> int:
    """Count immediate subfolders + assets in a folder."""
    subfolder_count = (
        db.query(func.count(Folder.id))
        .filter(Folder.parent_id == folder_id, Folder.deleted_at.is_(None))
        .scalar()
        or 0
    )
    asset_count = len(_asset_ids_in_folder(db, folder_id))
    return subfolder_count + asset_count


def _folder_to_response(db: Session, folder: Folder) -> FolderResponse:
    resp = FolderResponse.model_validate(folder)
    resp.item_count = _compute_item_count(db, folder.id)
    return resp


def _get_descendant_ids_including_deleted(db: Session, folder_id: uuid.UUID) -> list[uuid.UUID]:
    """Get all descendant folder IDs including soft-deleted ones."""
    descendants: list[uuid.UUID] = []
    queue = [folder_id]
    while queue:
        current = queue.pop(0)
        children = db.query(Folder.id).filter(Folder.parent_id == current).all()
        for (child_id,) in children:
            if child_id not in descendants:
                descendants.append(child_id)
                queue.append(child_id)
    return descendants


def _max_subtree_depth(db: Session, folder_id: uuid.UUID) -> int:
    """Get the max depth of the subtree rooted at folder_id."""
    max_depth = 0
    queue: list[tuple[uuid.UUID, int]] = [(folder_id, 0)]
    while queue:
        current, depth = queue.pop(0)
        children = (
            db.query(Folder.id)
            .filter(Folder.parent_id == current, Folder.deleted_at.is_(None))
            .all()
        )
        for (child_id,) in children:
            child_depth = depth + 1
            if child_depth > max_depth:
                max_depth = child_depth
            queue.append((child_id, child_depth))
    return max_depth


# ─── CRUD ─────────────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/folders",
    response_model=FolderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_folder(
    project_id: uuid.UUID,
    body: FolderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_role(db, project_id, current_user, ProjectRole.editor)

    # Validate parent exists and belongs to project
    if body.parent_id:
        parent = _get_folder(db, body.parent_id)
        if parent.project_id != project_id:
            raise HTTPException(status_code=400, detail="Parent folder not in this project")
        # Check depth
        depth = _get_depth(db, body.parent_id)
        if depth >= MAX_FOLDER_DEPTH:
            raise HTTPException(
                status_code=400,
                detail=f"Maximum folder depth of {MAX_FOLDER_DEPTH} exceeded",
            )

    folder = Folder(
        project_id=project_id,
        parent_id=body.parent_id,
        name=body.name,
        created_by=current_user.id,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return _folder_to_response(db, folder)


@router.get("/projects/{project_id}/folders", response_model=list[FolderResponse])
def list_folders(
    project_id: uuid.UUID,
    parent_id: Optional[str] = Query(None, description="Filter by parent_id. 'root' for root level."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Allow access if user is a project member OR the project is public
    member = get_project_member(db, project_id, current_user.id)
    if not member and not is_public_project(db, project_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a project member")

    query = db.query(Folder).filter(
        Folder.project_id == project_id,
        Folder.deleted_at.is_(None),
    )

    if parent_id == "root":
        query = query.filter(Folder.parent_id.is_(None))
    elif parent_id is not None:
        query = query.filter(Folder.parent_id == uuid.UUID(parent_id))

    folders = query.order_by(Folder.created_at.desc()).all()
    return [_folder_to_response(db, f) for f in folders]


@router.get("/projects/{project_id}/folder-tree", response_model=list[FolderTreeNode])
def get_folder_tree(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Allow access if user is a project member OR the project is public
    member = get_project_member(db, project_id, current_user.id)
    if not member and not is_public_project(db, project_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a project member")

    all_folders = (
        db.query(Folder)
        .filter(Folder.project_id == project_id, Folder.deleted_at.is_(None))
        .all()
    )

    # Batch-compute item counts (avoid N+1 queries)
    folder_ids = [f.id for f in all_folders]

    subfolder_counts = dict(
        db.query(Folder.parent_id, func.count(Folder.id))
        .filter(Folder.parent_id.in_(folder_ids), Folder.deleted_at.is_(None))
        .group_by(Folder.parent_id)
        .all()
    ) if folder_ids else {}

    # Distinct assets per folder, counting via either the asset's own
    # (primary) folder_id or any version individually filed there - see
    # _asset_ids_in_folder / AssetVersion.folder_id on the model. Deduped in
    # Python per folder since an asset can satisfy both sources for the same
    # folder (its primary folder and its first version's folder usually
    # coincide) and must still only count once there.
    asset_counts: dict[uuid.UUID, int] = {}
    if folder_ids:
        own_pairs = db.query(Asset.folder_id, Asset.id).filter(
            Asset.folder_id.in_(folder_ids), Asset.deleted_at.is_(None)
        )
        version_pairs = db.query(AssetVersion.folder_id, AssetVersion.asset_id).filter(
            AssetVersion.folder_id.in_(folder_ids), AssetVersion.deleted_at.is_(None)
        )
        asset_ids_by_folder: dict[uuid.UUID, set] = {}
        for fid, aid in own_pairs.union(version_pairs).all():
            asset_ids_by_folder.setdefault(fid, set()).add(aid)
        asset_counts = {fid: len(ids) for fid, ids in asset_ids_by_folder.items()}

    # Build tree in Python
    folder_map: dict[uuid.UUID, FolderTreeNode] = {}
    for f in all_folders:
        folder_map[f.id] = FolderTreeNode(
            id=f.id,
            name=f.name,
            parent_id=f.parent_id,
            item_count=(subfolder_counts.get(f.id, 0) + asset_counts.get(f.id, 0)),
        )

    roots: list[FolderTreeNode] = []
    for node in folder_map.values():
        if node.parent_id and node.parent_id in folder_map:
            folder_map[node.parent_id].children.append(node)
        else:
            roots.append(node)

    return roots


@router.patch("/folders/{folder_id}", response_model=FolderResponse)
def update_folder(
    folder_id: uuid.UUID,
    body: FolderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = _get_folder(db, folder_id)
    require_project_role(db, folder.project_id, current_user, ProjectRole.editor)

    if body.name is not None:
        folder.name = body.name

    # Handle parent_id move (only if explicitly set)
    if "parent_id" in body.model_fields_set:
        new_parent_id = body.parent_id
        if new_parent_id is not None:
            # Can't move into self or descendant
            descendants = _get_descendant_ids(db, folder_id)
            if new_parent_id == folder_id or new_parent_id in descendants:
                raise HTTPException(status_code=400, detail="Cannot move folder into itself or a subfolder")
            parent = _get_folder(db, new_parent_id)
            if parent.project_id != folder.project_id:
                raise HTTPException(status_code=400, detail="Target folder not in same project")
            # Check depth
            depth = _get_depth(db, new_parent_id)
            max_subtree = _max_subtree_depth(db, folder_id)
            if depth + max_subtree + 1 > MAX_FOLDER_DEPTH:
                raise HTTPException(
                    status_code=400,
                    detail=f"Move would exceed maximum folder depth of {MAX_FOLDER_DEPTH}",
                )
        folder.parent_id = new_parent_id

    db.commit()
    db.refresh(folder)
    return _folder_to_response(db, folder)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(
    folder_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = _get_folder(db, folder_id)
    require_project_role(db, folder.project_id, current_user, ProjectRole.editor)

    now = datetime.now(timezone.utc)

    # Cascade soft-delete: folder + all descendants + their assets
    all_folder_ids = [folder_id] + _get_descendant_ids(db, folder_id)

    db.query(Folder).filter(Folder.id.in_(all_folder_ids)).update(
        {"deleted_at": now}, synchronize_session="fetch"
    )
    db.query(Asset).filter(Asset.folder_id.in_(all_folder_ids)).update(
        {"deleted_at": now}, synchronize_session="fetch"
    )

    db.commit()


# ─── Move ─────────────────────────────────────────────────────────────────────


@router.patch("/assets/{asset_id}/move", response_model=dict)
def move_asset(
    asset_id: uuid.UUID,
    body: AssetMoveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    require_project_role(db, asset.project_id, current_user, ProjectRole.editor)

    if body.folder_id is not None:
        target = _get_folder(db, body.folder_id)
        if target.project_id != asset.project_id:
            raise HTTPException(status_code=400, detail="Target folder not in same project")

    asset.folder_id = body.folder_id
    db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/bulk-move", response_model=dict)
def bulk_move(
    project_id: uuid.UUID,
    body: BulkMoveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_role(db, project_id, current_user, ProjectRole.editor)

    # Validate target folder
    if body.target_folder_id is not None:
        target = _get_folder(db, body.target_folder_id)
        if target.project_id != project_id:
            raise HTTPException(status_code=400, detail="Target folder not in this project")

    # Move assets
    if body.asset_ids:
        assets = (
            db.query(Asset)
            .filter(
                Asset.id.in_(body.asset_ids),
                Asset.project_id == project_id,
                Asset.deleted_at.is_(None),
            )
            .all()
        )
        if len(assets) != len(body.asset_ids):
            raise HTTPException(status_code=400, detail="Some assets not found in this project")
        for a in assets:
            a.folder_id = body.target_folder_id

    # Move folders
    if body.folder_ids:
        descendants = set()
        if body.target_folder_id:
            descendants = set(_get_descendant_ids(db, body.target_folder_id))
            descendants.add(body.target_folder_id)

        folders = (
            db.query(Folder)
            .filter(
                Folder.id.in_(body.folder_ids),
                Folder.project_id == project_id,
                Folder.deleted_at.is_(None),
            )
            .all()
        )
        if len(folders) != len(body.folder_ids):
            raise HTTPException(status_code=400, detail="Some folders not found in this project")

        for f in folders:
            if f.id in descendants or f.id == body.target_folder_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot move folder '{f.name}' into itself or a subfolder",
                )
            f.parent_id = body.target_folder_id

    db.commit()
    return {"ok": True, "moved_assets": len(body.asset_ids), "moved_folders": len(body.folder_ids)}


# ─── Trash & Restore ─────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/trash", response_model=dict)
def list_trash(
    project_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_role(db, project_id, current_user, ProjectRole.editor)

    deleted_folders = (
        db.query(Folder)
        .filter(Folder.project_id == project_id, Folder.deleted_at.isnot(None))
        .order_by(Folder.deleted_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    deleted_assets = (
        db.query(Asset)
        .filter(Asset.project_id == project_id, Asset.deleted_at.isnot(None))
        .order_by(Asset.deleted_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "folders": [
            {
                "id": str(f.id),
                "name": f.name,
                "type": "folder",
                "parent_id": str(f.parent_id) if f.parent_id else None,
                "deleted_at": f.deleted_at.isoformat() if f.deleted_at else None,
            }
            for f in deleted_folders
        ],
        "assets": [
            {
                "id": str(a.id),
                "name": a.name,
                "type": a.asset_type,
                "folder_id": str(a.folder_id) if a.folder_id else None,
                "deleted_at": a.deleted_at.isoformat() if a.deleted_at else None,
            }
            for a in deleted_assets
        ],
    }


@router.post("/assets/{asset_id}/restore", response_model=dict)
def restore_asset(
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.isnot(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Deleted asset not found")

    require_project_role(db, asset.project_id, current_user, ProjectRole.editor)

    # A deleted project has no restore path, so restoring an asset into a soft-deleted project would be
    # a false success — the retention GC's project cascade would silently hard-delete it. Refuse.
    project = db.query(Project).filter(Project.id == asset.project_id).first()
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Cannot restore: the project has been deleted")

    # If parent folder is deleted, move to root
    if asset.folder_id:
        parent_folder = (
            db.query(Folder)
            .filter(Folder.id == asset.folder_id, Folder.deleted_at.is_(None))
            .first()
        )
        if not parent_folder:
            asset.folder_id = None

    asset.deleted_at = None
    db.commit()
    return {"ok": True}


@router.post("/folders/{folder_id}/restore", response_model=dict)
def restore_folder(
    folder_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = db.query(Folder).filter(Folder.id == folder_id, Folder.deleted_at.isnot(None)).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Deleted folder not found")

    require_project_role(db, folder.project_id, current_user, ProjectRole.editor)

    project = db.query(Project).filter(Project.id == folder.project_id).first()
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Cannot restore: the project has been deleted")

    # If parent folder is deleted, restore to root
    if folder.parent_id:
        parent = (
            db.query(Folder)
            .filter(Folder.id == folder.parent_id, Folder.deleted_at.is_(None))
            .first()
        )
        if not parent:
            folder.parent_id = None

    # Restore folder and all its descendants + their assets
    folder.deleted_at = None
    descendant_ids = _get_descendant_ids_including_deleted(db, folder_id)
    all_ids = [folder_id] + descendant_ids

    db.query(Folder).filter(Folder.id.in_(all_ids)).update(
        {"deleted_at": None}, synchronize_session="fetch"
    )
    db.query(Asset).filter(Asset.folder_id.in_(all_ids), Asset.deleted_at.isnot(None)).update(
        {"deleted_at": None}, synchronize_session="fetch"
    )

    db.commit()
    return {"ok": True}


@router.get("/folders/{folder_id}/download")
def download_folder(
    folder_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Zips this folder and its subfolders and streams it back for download -
    see the "..." folder menu in the web UI. Two sources, tried in order:

    1. **The original NAS delivery directory**, if this project is
       Ayon-linked and the folder's real on-disk path (reconstructed from its
       FreeFrame Folder ancestry under the project's `clientROOTS` root)
       actually exists - zips *everything* there, including files the Ayon
       Client Delivery Watcher deliberately didn't ingest (e.g. the plain
       movie / reference PNG next to a burn-in variant). Staged in
       `{clientROOTS}/{project}/temp/<timestamp>/` rather than a local temp
       dir, so it lives alongside the delivery itself.
    2. **FreeFrame's own S3 storage** (fallback for non-Ayon-linked folders,
       or if the NAS path isn't reachable from this machine) - zips each
       asset's latest version (the original uploaded file, not the
       transcoded HLS renditions), i.e. only whatever actually made it into
       FreeFrame. Staged in the OS temp dir.

    Zip filename mirrors the folder's own place in the tree: up to two
    ancestor folder names plus its own, root-to-leaf
    (e.g. folder "v003" under .../111/Animation/v003 -> "111_Animation_v003.zip"),
    matching the shot/task/version structure the Ayon Client Delivery
    Watcher mirrors into FreeFrame - falls back to fewer segments for
    shallower folders.
    """
    import io
    import tempfile
    import zipfile
    from pathlib import Path
    from datetime import datetime as dt
    from starlette.background import BackgroundTask
    from fastapi.responses import FileResponse
    from ..services.s3_service import get_s3_client
    from ..services import ayon_service
    from ..config import settings

    folder = _get_folder(db, folder_id)
    member = get_project_member(db, folder.project_id, current_user.id)
    if not member and not is_public_project(db, folder.project_id) and not current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Access denied")

    def _sanitize(name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "folder"

    # ── Try the original NAS delivery directory first ───────────────────────
    project = db.query(Project).filter(Project.id == folder.project_id).first()
    if project and project.ayon_project_name:
        try:
            client_root = ayon_service.get_project_client_delivery_path(project.ayon_project_name)
        except Exception:
            client_root = None
        if client_root:
            ancestor_names = []
            cursor = folder
            while cursor:
                ancestor_names.append(cursor.name)
                cursor = db.query(Folder).filter(Folder.id == cursor.parent_id).first() if cursor.parent_id else None
            ancestor_names.reverse()
            physical_path = Path(client_root, *ancestor_names)
            if physical_path.is_dir():
                zip_base_name = _folder_zip_basename(db, folder, _sanitize)
                timestamp_dir = dt.now().strftime("%Y%m%d_%H%M%S")
                tmp_dir = Path(client_root) / "temp" / timestamp_dir
                tmp_dir.mkdir(parents=True, exist_ok=True)
                zip_path = tmp_dir / f"{zip_base_name}.zip"
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in physical_path.rglob("*"):
                        if f.is_file():
                            zf.write(f, arcname=str(f.relative_to(physical_path)))

                def _cleanup_nas():
                    try:
                        zip_path.unlink(missing_ok=True)
                        tmp_dir.rmdir()
                    except OSError:
                        pass  # not empty / already gone - the beat sweep catches stragglers

                return FileResponse(
                    path=zip_path,
                    filename=zip_path.name,
                    media_type="application/zip",
                    background=BackgroundTask(_cleanup_nas),
                )

    # ── Fallback: whatever actually made it into FreeFrame ──────────────────
    descendant_ids = _get_descendant_ids(db, folder_id)
    folder_ids = [folder_id] + descendant_ids
    assets = db.query(Asset).filter(Asset.folder_id.in_(folder_ids), Asset.deleted_at.is_(None)).all()
    if not assets:
        raise HTTPException(status_code=404, detail="This folder has no files to download")

    # Relative path (within the zip) for each folder in the subtree, rooted
    # at the downloaded folder itself (which maps to "" - its own files sit
    # at the zip's top level, not nested one level deeper into a folder
    # named after itself). Every subfolder - including sibling folders that
    # happen to share a name, e.g. two different "v001"s under different
    # tasks - gets its own real nested path, so files from different
    # folders never collide or get silently flattened together.
    folder_by_id = {folder.id: folder}
    for f in db.query(Folder).filter(Folder.id.in_(descendant_ids)).all():
        folder_by_id[f.id] = f

    rel_path_by_folder_id: dict[uuid.UUID, str] = {folder_id: ""}

    def _rel_path(fid: uuid.UUID) -> str:
        if fid in rel_path_by_folder_id:
            return rel_path_by_folder_id[fid]
        f = folder_by_id.get(fid)
        if not f or not f.parent_id:
            rel_path_by_folder_id[fid] = _sanitize(f.name) if f else ""
            return rel_path_by_folder_id[fid]
        parent_path = _rel_path(f.parent_id)
        name = _sanitize(f.name)
        path = f"{parent_path}/{name}" if parent_path else name
        rel_path_by_folder_id[fid] = path
        return path

    for fid in folder_by_id:
        _rel_path(fid)

    asset_ids = [a.id for a in assets]
    latest_versions = {}  # asset_id -> AssetVersion
    for v in (
        db.query(AssetVersion)
        .filter(AssetVersion.asset_id.in_(asset_ids), AssetVersion.deleted_at.is_(None))
        .order_by(AssetVersion.version_number.desc())
        .all()
    ):
        latest_versions.setdefault(v.asset_id, v)

    version_ids = [v.id for v in latest_versions.values()]
    files_by_version: dict[uuid.UUID, list] = {}
    for f in db.query(MediaFile).filter(MediaFile.version_id.in_(version_ids)).all():
        files_by_version.setdefault(f.version_id, []).append(f)

    zip_base_name = _folder_zip_basename(db, folder, _sanitize)

    timestamp_dir = dt.now().strftime("%Y%m%d_%H%M%S")
    tmp_dir = Path(tempfile.gettempdir()) / "freeframe_downloads" / timestamp_dir
    tmp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = tmp_dir / f"{zip_base_name}.zip"

    s3 = get_s3_client()
    used_names: dict[str, set[str]] = {}  # folder path -> filenames already placed there
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for asset in assets:
            version = latest_versions.get(asset.id)
            if not version:
                continue
            folder_path = rel_path_by_folder_id.get(asset.folder_id, "") if asset.folder_id else ""
            names_here = used_names.setdefault(folder_path, set())
            for media_file in files_by_version.get(version.id, []):
                buf = io.BytesIO()
                try:
                    s3.download_fileobj(settings.s3_bucket, media_file.s3_key_raw, buf)
                except Exception:
                    continue
                filename = _sanitize(media_file.original_filename or asset.name)
                if filename in names_here:
                    stem, dot, ext = filename.rpartition(".")
                    filename = f"{stem or filename}_{asset.id}{dot}{ext}"
                names_here.add(filename)
                arcname = f"{folder_path}/{filename}" if folder_path else filename
                zf.writestr(arcname, buf.getvalue())

    def _cleanup():
        try:
            zip_path.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass  # not empty / already gone - harmless, OS temp dir gets cleaned eventually anyway

    return FileResponse(
        path=zip_path,
        filename=zip_path.name,
        media_type="application/zip",
        background=BackgroundTask(_cleanup),
    )
