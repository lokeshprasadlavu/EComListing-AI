# drive_db.py
import io
import time
import functools
import streamlit as st
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# -------------------------------------------------------------------------
# Custom Exception
# -------------------------------------------------------------------------
class DriveDBError(Exception):
    """Raised when a Google Drive operation fails after retries."""
    pass

# -------------------------------------------------------------------------
# Globals
# -------------------------------------------------------------------------
_drive_service = None  # set by app.py via set_drive_service()
DRIVE_FOLDER_ID = None

# -------------------------------------------------------------------------
# Retry Decorator
# -------------------------------------------------------------------------
def _with_retries(retries=3, delay=2):
    """Decorator to retry a Drive call up to `retries` times with `delay` sec."""
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, retries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    time.sleep(delay)
            raise DriveDBError(f"'{fn.__name__}' failed after {retries} attempts: {last_exc}")
        return wrapper
    return dec

# -------------------------------------------------------------------------
# Initialization Helpers
# -------------------------------------------------------------------------
def set_drive_service(svc):
    """Inject a preconfigured googleapiclient.discovery.Resource."""
    global _drive_service
    _drive_service = svc

def _get_service():
    if _drive_service is None:
        raise DriveDBError("Drive service not initialized; call set_drive_service first.")
    return _drive_service

# -------------------------------------------------------------------------
# Core API (wrapped with retries)
# -------------------------------------------------------------------------
@_with_retries()
def list_files(mime_filter=None, parent_id=None):
    svc = _get_service()
    pid = parent_id or DRIVE_FOLDER_ID
    q = f"'{pid}' in parents and trashed = false"
    if mime_filter:
        q += f" and mimeType contains '{mime_filter}'"
    resp = svc.files().list(q=q, fields="files(id,name,mimeType)").execute()
    return resp.get("files", [])

@_with_retries()
def download_file(file_id):
    svc = _get_service()
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl  = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return buf

@_with_retries()
def upload_file(name, data, mime_type, parent_id=None):
    svc = _get_service()
    pid = parent_id or DRIVE_FOLDER_ID
    # check existing
    existing = svc.files().list(
        q=f"name='{name}' and '{pid}' in parents and trashed = false",
        fields="files(id)"
    ).execute().get("files", [])
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type)
    if existing:
        return svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        meta = {"name": name, "parents": [pid]}
        return svc.files().create(body=meta, media_body=media).execute()

@_with_retries()
def find_folder(name, parent_id=None):
    svc = _get_service()
    pid = parent_id or DRIVE_FOLDER_ID
    q = (
        f"name='{name}' "
        "and mimeType='application/vnd.google-apps.folder' "
        f"and '{pid}' in parents and trashed=false"
    )
    resp = svc.files().list(q=q, fields="files(id)").execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None

@_with_retries()
def create_folder(name, parent_id=None):
    svc = _get_service()
    pid = parent_id or DRIVE_FOLDER_ID
    meta = {
        "name":     name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents":  [pid],
    }
    folder = svc.files().create(body=meta, fields="id").execute()
    return folder["id"]

def find_or_create_folder(name, parent_id=None):
    """
    Try to find folder, else create it.
    Retries apply to underlying calls.
    """
    try:
        fid = find_folder(name, parent_id)
    except DriveDBError:
        fid = None
    return fid if fid else create_folder(name, parent_id)
