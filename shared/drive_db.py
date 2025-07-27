import io
import time
import random
import functools
import mimetypes
from typing import Optional, List
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from googleapiclient.errors import HttpError

# -------------------------------------------------------------------------
# Custom Exception
# -------------------------------------------------------------------------
class DriveDBError(Exception):
    """Raised when a Google Drive operation fails after retries."""
    pass

# -------------------------------------------------------------------------
# Globals
# -------------------------------------------------------------------------
_drive_service = None
DRIVE_FOLDER_ID = None

# -------------------------------------------------------------------------
# Retry Decorator with Backoff + Filtering
# -------------------------------------------------------------------------
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}

def _with_retries(retries=3, delay=1.5):
    def dec(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, retries + 1):
                try:
                    return fn(*args, **kwargs)
                except HttpError as e:
                    if e.resp.status not in RETRYABLE_HTTP_STATUSES:
                        raise
                    last_exc = e
                except Exception as e:
                    last_exc = e
                sleep = delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                time.sleep(sleep)
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
# Core API
# -------------------------------------------------------------------------
@_with_retries()
def list_files(mime_filter: Optional[str] = None, parent_id: Optional[str] = None) -> List[dict]:
    """List all files in a folder, optionally filtered by mimeType."""
    svc = _get_service()
    pid = parent_id or DRIVE_FOLDER_ID
    q = f"'{pid}' in parents and trashed = false"
    if mime_filter:
        q += f" and mimeType contains '{mime_filter}'"
    resp = svc.files().list(q=q, fields="files(id,name,mimeType)").execute()
    return resp.get("files", [])

@_with_retries()
def download_file(file_id: str) -> io.BytesIO:
    """Download a file by ID and return its contents as BytesIO."""
    svc = _get_service()
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return buf

@_with_retries()
def upload_file(name: str, data: bytes, mime_type: Optional[str] = None, parent_id: Optional[str] = None):
    """Upload a file, replacing it if the name already exists in the folder."""
    svc = _get_service()
    pid = parent_id or DRIVE_FOLDER_ID
    mime_type = mime_type or _guess_mime_type(name)

    # Check if a file with this name already exists
    existing = svc.files().list(
        q=f"name='{name}' and '{pid}' in parents and trashed = false",
        fields="files(id)"
    ).execute().get("files", [])

    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type)
    metadata = {"name": name, "parents": [pid]}

    if existing:
        return svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        return svc.files().create(body=metadata, media_body=media).execute()

@_with_retries()
def find_folder(name: str, parent_id: Optional[str] = None) -> Optional[str]:
    """Find a folder by name under parent_id and return its ID, or None."""
    svc = _get_service()
    pid = parent_id or DRIVE_FOLDER_ID
    q = (
        f"name='{name}' "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and '{pid}' in parents and trashed = false"
    )
    resp = svc.files().list(q=q, fields="files(id)").execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None

@_with_retries()
def create_folder(name: str, parent_id: Optional[str] = None) -> str:
    """Create a new folder under parent_id and return its ID."""
    svc = _get_service()
    pid = parent_id or DRIVE_FOLDER_ID
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [pid]
    }
    folder = svc.files().create(body=meta, fields="id").execute()
    return folder["id"]

def find_or_create_folder(name: str, parent_id: Optional[str] = None) -> str:
    """Find a folder by name or create it if it doesn't exist."""
    try:
        fid = find_folder(name, parent_id)
    except DriveDBError:
        fid = None
    return fid or create_folder(name, parent_id)

# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def _guess_mime_type(name: str) -> str:
    mime, _ = mimetypes.guess_type(name)
    return mime or "application/octet-stream"
