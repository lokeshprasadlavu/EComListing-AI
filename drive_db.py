import io
import os
import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# -----------------------------------------------------------------------------
# Globals
# -----------------------------------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/drive"]
DRIVE_FOLDER_ID = None       # set by app.py
_drive_service = None        # will hold either SA or OAuth client
_use_oauth = False           # toggles which auth to use

# -----------------------------------------------------------------------------
# Initialization
# -----------------------------------------------------------------------------
def init_with_oauth(drive_service):
    """Call this from app.py after running the OAuth flow."""
    global _drive_service, _use_oauth
    _drive_service = drive_service
    _use_oauth = True

def _get_service_account_client():
    """Builds a Drive service using the service-account in secrets."""
    sa_info = st.secrets["drive_service_account"]
    creds   = service_account.Credentials.from_service_account_info(
        sa_info, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)

def _get_drive_service():
    """Returns the active Drive service (OAuth if initialized, else SA)."""
    if _use_oauth and _drive_service is not None:
        return _drive_service
    return _get_service_account_client()

# -----------------------------------------------------------------------------
# Core API functions
# -----------------------------------------------------------------------------
def list_files(mime_filter=None, parent_id=None):
    svc = _get_drive_service()
    pid = parent_id or DRIVE_FOLDER_ID
    q = f"'{pid}' in parents and trashed = false"
    if mime_filter:
        q += f" and mimeType contains '{mime_filter}'"
    resp = svc.files().list(q=q, fields="files(id,name,mimeType)").execute()
    return resp.get("files", [])

def download_file(file_id):
    svc = _get_drive_service()
    request = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf

def upload_file(name, data, mime_type, parent_id=None):
    svc = _get_drive_service()
    pid = parent_id or DRIVE_FOLDER_ID

    # Check for existing file
    existing = svc.files().list(
        q=f"name='{name}' and '{pid}' in parents and trashed = false",
        fields="files(id)"
    ).execute().get("files", [])

    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type)
    if existing:
        return svc.files().update(
            fileId=existing[0]["id"], media_body=media
        ).execute()
    else:
        metadata = {"name": name, "parents": [pid]}
        return svc.files().create(
            body=metadata, media_body=media
        ).execute()

def find_folder(name, parent_id=None):
    svc = _get_drive_service()
    pid = parent_id or DRIVE_FOLDER_ID
    q = (
        f"name='{name}' "
        "and mimeType='application/vnd.google-apps.folder' "
        f"and '{pid}' in parents and trashed=false"
    )
    resp = svc.files().list(q=q, fields="files(id)").execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None

def create_folder(name, parent_id=None):
    svc = _get_drive_service()
    pid = parent_id or DRIVE_FOLDER_ID
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [pid],
    }
    folder = svc.files().create(body=metadata, fields="id").execute()
    return folder["id"]

def find_or_create_folder(name, parent_id=None):
    fid = find_folder(name, parent_id)
    return fid if fid else create_folder(name, parent_id)
