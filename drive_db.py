import io, json, os, streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
# This will be populated from your config loader or st.secrets:
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")

def get_drive_service():
    # Load service-account key from Streamlit secrets
    sa_info = json.loads(st.secrets["drive_service_account"]["key"])
    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)

def list_files(mimeType_filter=None):
    svc = get_drive_service()
    q = f"'{DRIVE_FOLDER_ID}' in parents and trashed = false"
    if mimeType_filter:
        q += f" and mimeType = '{mimeType_filter}'"
    resp = svc.files().list(q=q, fields="files(id,name,mimeType)").execute()
    return resp.get("files", [])

def download_file(file_id: str) -> io.BytesIO:
    svc = get_drive_service()
    request = svc.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return fh

def upload_file(name: str, data: bytes, mime_type: str):
    svc = get_drive_service()
    # try to find existing file
    existing = svc.files().list(
        q=f"name='{name}' and '{DRIVE_FOLDER_ID}' in parents",
        fields="files(id)"
    ).execute().get("files", [])
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type)
    if existing:
        return svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        meta = {"name": name, "parents": [DRIVE_FOLDER_ID]}
        return svc.files().create(body=meta, media_body=media).execute()
