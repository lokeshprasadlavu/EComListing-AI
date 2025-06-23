import io
import os
import pickle
import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# -----------------------------------------------------------------------------
# Globals
# -----------------------------------------------------------------------------
SCOPES_SERVICE    = ["https://www.googleapis.com/auth/drive"]
SCOPES_OAUTH      = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_FOLDER_ID   = None       # to be set by app.py
_drive_service    = None        # holds the active Drive client
_TOKEN_FILE       = "drive_token.pickle"

# -----------------------------------------------------------------------------
# Initialization
# -----------------------------------------------------------------------------
def init(provider: str, **kwargs):
    """
    Initialize the Drive client.
      provider: "service_account" or "oauth"
      kwargs:
        if service_account: sa_info=<dict>
        if oauth:           oauth_service=<Resource>
    """
    global _drive_service

    if provider == "service_account":
        sa_info = kwargs.get("sa_info")
        if not isinstance(sa_info, dict):
            raise ValueError("service_account init requires sa_info=dict")
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=SCOPES_SERVICE
        )
        _drive_service = build("drive", "v3", credentials=creds)

    elif provider == "oauth":
        oauth_svc = kwargs.get("oauth_service")
        if oauth_svc is None:
            raise ValueError("oauth init requires oauth_service")
        _drive_service = oauth_svc

    else:
        raise ValueError(f"Unknown Drive init provider: {provider}")

def _get_service():
    if _drive_service is None:
        raise RuntimeError("drive_db not initialized; call drive_db.init(...) first")
    return _drive_service

def init_from_secrets():
    """
    Auto initialize from Streamlit secrets.
    Prefers OAuth if [oauth_client] exists, else falls back to service-account.
    """
    # Attempt OAuth first
    oauth_cfg = st.secrets.get("oauth_client", None)
    if oauth_cfg:
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
        except ImportError as e:
            st.error("Missing OAuth libraries; install google-auth-oauthlib")
            st.stop()

        creds = None
        if os.path.exists(_TOKEN_FILE):
            try:
                with open(_TOKEN_FILE, "rb") as f:
                    creds = pickle.load(f)
            except Exception:
                creds = None

        if not creds or not getattr(creds, "valid", False):
            if creds and getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_config(oauth_cfg, SCOPES_OAUTH)
                creds = flow.run_local_server(port=0)
            with open(_TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)

        oauth_service = build("drive", "v3", credentials=creds)
        init("oauth", oauth_service=oauth_service)
        return

    # Fallback to service-account
    sa_info = st.secrets.get("drive_service_account", None)
    if sa_info:
        init("service_account", sa_info=sa_info)
        return

    st.error("No Drive credentials found in .streamlit/secrets.toml")
    st.stop()

# -----------------------------------------------------------------------------
# Core API functions
# -----------------------------------------------------------------------------
def list_files(mime_filter=None, parent_id=None):
    svc = _get_service()
    pid = parent_id or DRIVE_FOLDER_ID
    q = f"'{pid}' in parents and trashed=false"
    if mime_filter:
        q += f" and mimeType contains '{mime_filter}'"
    resp = svc.files().list(q=q, fields="files(id,name,mimeType)").execute()
    return resp.get("files", [])

def download_file(file_id):
    svc = _get_service()
    request = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf

def upload_file(name, data, mime_type, parent_id=None):
    svc = _get_service()
    pid = parent_id or DRIVE_FOLDER_ID

    existing = svc.files().list(
        q=f"name='{name}' and '{pid}' in parents and trashed=false",
        fields="files(id)"
    ).execute().get("files", [])

    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type)
    if existing:
        return svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        metadata = {"name": name, "parents": [pid]}
        return svc.files().create(body=metadata, media_body=media).execute()

def find_folder(name, parent_id=None):
    svc = _get_service()
    pid = parent_id or DRIVE_FOLDER_ID
    q = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{pid}' in parents and trashed=false"
    )
    resp = svc.files().list(q=q, fields="files(id)").execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None

def create_folder(name, parent_id=None):
    svc = _get_service()
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
