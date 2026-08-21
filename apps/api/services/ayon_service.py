"""Ayon integration via the official ayon-python-api SDK - live reads only,
nothing persisted in FreeFrame's own database.

Ported from D:\\pinokio\\api\\Ayon_Planner_v2.3.5.1\\app\\main.py, which already
has a working FastAPI app talking to this same Ayon server: connection setup
(ayon_api.ServerAPI(url, token=api_key)), folder+task listing
(get_folders()/get_tasks(), richer than the raw /hierarchy REST endpoint's
taskNames-only shape - real task ids/status/assignees), and physical-disk-path
resolution from a project's anatomy roots (get_physical_path() in main.py).
"""
import logging
import shutil
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import ayon_api

from ..config import settings

log = logging.getLogger("apps.api.ayon_service")


class AyonNotConfigured(Exception):
    pass


_lock = threading.Lock()
_connection: ayon_api.ServerAPI | None = None
_connection_key: tuple | None = None


def _resolve_credentials() -> tuple[str | None, str | None]:
    """The DB-stored override (Settings > Admin > Ayon Projects) takes
    precedence over the Pinokio launcher's AYON_URL/AYON_API_KEY env config,
    so an admin can repoint or rotate the connection without a restart."""
    from ..database import SessionLocal
    from ..models.instance_settings import InstanceSettings

    db = SessionLocal()
    try:
        row = db.query(InstanceSettings).first()
    finally:
        db.close()

    url = (row.ayon_url if row else None) or settings.ayon_url
    api_key = (row.ayon_api_key if row else None) or settings.ayon_api_key
    return url, api_key


def reset_connection() -> None:
    """Drop the cached SDK connection so the next call re-reads credentials
    (called after PUT /admin/ayon/connection updates the DB override)."""
    global _connection, _connection_key
    with _lock:
        _connection = None
        _connection_key = None


def _get_connection() -> ayon_api.ServerAPI:
    url, api_key = _resolve_credentials()
    if not url or not api_key:
        raise AyonNotConfigured("Ayon is not configured (ayon_url/ayon_api_key are unset)")

    global _connection, _connection_key
    key = (url, api_key)
    with _lock:
        if _connection is None or _connection_key != key:
            _connection = ayon_api.ServerAPI(url, token=api_key)
            _connection_key = key
        return _connection


def list_projects(active_only: bool = True) -> list[dict]:
    """Ayon projects, each {name, code, active, ...}. active_only=False includes archived/test ones."""
    con = _get_connection()
    return list(con.get_projects(active=True if active_only else None, fields=["name", "code", "active"]))


def _platform_key() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return "darwin"


def _project_roots(con: ayon_api.ServerAPI, project_name: str) -> dict:
    """{root_name: {platform: path, ...}} straight from the project's live anatomy.

    Not exposed via get_folders()/get_tasks() (those are GraphQL entity
    queries) - anatomy is a separate REST resource, fetched with the SDK's
    low-level authenticated con.get() the same way Ayon_Planner's
    get_physical_path() does.
    """
    res = con.get(f"projects/{project_name}/anatomy")
    if res.status_code != 200:
        return {}
    roots_data = (res.data or {}).get("roots", [])
    if isinstance(roots_data, list):
        return {r["name"]: r for r in roots_data if isinstance(r, dict) and r.get("name")}
    if isinstance(roots_data, dict):
        return roots_data
    return {}


def get_project_work_root(project_name: str) -> str | None:
    """This project's 'work' root path for the current OS (e.g. the mapped NAS drive)."""
    con = _get_connection()
    roots = _project_roots(con, project_name)
    work_root = roots.get("work") or (next(iter(roots.values())) if roots else None)
    if not work_root:
        return None
    return work_root.get(_platform_key())


def get_project_disk_path(project_name: str) -> str | None:
    """Where this project lives on disk, e.g. 'V:/26006_ACEID_HUAWEI'."""
    work_root = get_project_work_root(project_name)
    return f"{work_root.rstrip('/')}/{project_name}" if work_root else None


def get_project_client_delivery_path(project_name: str) -> str | None:
    """Where this project's DELIVERY_CLIENT_FREEFRAME deliveries live on disk for
    the current OS, e.g. '\\\\Comet\\Clients/z_dummyTest' - same root
    scripts/ayon_client_watcher.py resolves for its own ingestion scan.
    Used by routers/folders.py's folder download to zip the *original*
    delivery directory (every file, including ones the watcher didn't
    ingest) rather than only what ended up in FreeFrame."""
    con = _get_connection()
    roots = _project_roots(con, project_name)
    client_root = roots.get("clientROOTS")
    if not client_root:
        return None
    path = client_root.get(_platform_key())
    return f"{path.rstrip('/')}/{project_name}" if path else None


def trash_move_client_delivery(project_name: str) -> str | None:
    """Used by the admin "delete project + NAS data" purge (routers/admin.py
    purge_project_now): moves a project's NAS client-delivery folder to a
    sibling _deleted/<name>_<timestamp> folder instead of erasing it, so the
    NAS side stays recoverable even though the FreeFrame DB/S3 side is hard-
    deleted. Best-effort - returns None (and logs) rather than raising, so a
    NAS hiccup never blocks the DB purge that follows it."""
    try:
        path = get_project_client_delivery_path(project_name)
        if not path:
            return None
        src = Path(path)
        if not src.exists():
            return None
        dest_dir = src.parent / "_deleted"
        dest_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        dest = dest_dir / f"{project_name}_{ts}"
        shutil.move(str(src), str(dest))
        return str(dest)
    except Exception:
        log.exception("trash_move_client_delivery(%r) failed - NAS folder left untouched", project_name)
        return None


def get_folders_and_tasks(project_name: str) -> list[dict]:
    """Full folder tree for one project. Each folder carries its real task
    objects (id, name, taskType, status, assignees) and its resolved physical
    disk path - built from get_folders()/get_tasks(), not the /hierarchy
    endpoint's simplified taskNames list.
    """
    con = _get_connection()

    folders = list(con.get_folders(
        project_name,
        fields=["id", "name", "parentId", "folderType", "path"],
    ))
    tasks = list(con.get_tasks(
        project_name,
        fields=["id", "name", "folderId", "taskType", "status", "assignees"],
    ))

    tasks_by_folder: dict[str, list[dict]] = {}
    for t in tasks:
        tasks_by_folder.setdefault(t.get("folderId"), []).append(t)

    project_root = get_project_disk_path(project_name)

    nodes: dict[str, dict] = {}
    for f in folders:
        folder_path = (f.get("path") or "").lstrip("/")
        nodes[f["id"]] = {
            "id": f["id"],
            "name": f["name"],
            "folderType": f.get("folderType"),
            "path": f.get("path"),
            "physical_path": f"{project_root}/{folder_path}" if project_root else None,
            "tasks": [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "taskType": t.get("taskType"),
                    "status": t.get("status"),
                    "assignees": t.get("assignees") or [],
                }
                for t in tasks_by_folder.get(f["id"], [])
            ],
            "children": [],
        }

    roots: list[dict] = []
    for f in folders:
        node = nodes[f["id"]]
        parent_id = f.get("parentId")
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)

    return roots
