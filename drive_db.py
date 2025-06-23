import io
import os
import pickle
import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# -----------------------------------------------------------------------------
# Globals
# -----------------------------------------------------------------------------
SCOPES_SERVICE  = ["https://www.googleapis.com/auth/drive"]
SCOPES_OAUTH    = ["https://www.googleapis.com/auth/drive"]
DRIVE_FOLDER_ID = None                # to be set by app.py
_drive_service  = None                # will hold the active Drive client

# -----------------------------------------------------------------------------
# Initialization helpers
# -----------------------------------------------------------------------------
def init(provider: str, **kwargs):
    """
    provider: "service_account" or "oauth"
    kwargs:
      - if service_account: sa_info=<dict>
      - if oauth:           oauth_service=<Resource>
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
        raise RuntimeError("drive_db not initialized; call drive_db.init_from_secrets() first")
    return _drive_service

# -----------------------------------------------------------------------------
# Auto‐init from Streamlit secrets
# -----------------------------------------------------------------------------
def init_from_secrets():
    """
    1) Try manual OAuth (refresh token from Playground in [oauth_manual])
    2) Else fall back to service-account ([drive_service_account])
    """
    manual = st.secrets.get("oauth_manual", None)
    if manual:
        # Build Credentials directly from your stored refresh token
        creds = Credentials(
            token=None,
            refresh_token=manual["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=manual["client_id"],
            client_secret=manual["client_secret"],
            scopes=SCOPES_OAUTH,
        )
        # Force a token refresh (so we have a valid access_token immediately)
        creds.refresh(Request())

        svc = build("drive", "v3", credentials=creds)
        init("oauth", oauth_service=svc)
        return

    # Service-account fallback
    sa_info = st.secrets.get("drive_service_account", None)
    if sa_info:
        init("service_account", sa_info=sa_info)
        return

    st.error("No Drive credentials found in secrets.toml (oauth_manual or drive_service_account)")
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
