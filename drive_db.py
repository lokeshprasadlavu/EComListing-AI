import io
import json
import os
import streamlit as st
import tempfile
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
drive_folder_id = None  # This will be set by app.py

def get_drive_service():
    sa_key = st.secrets["drive_service_account"]
    creds = service_account.Credentials.from_service_account_info(sa_key, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)

def list_files(mime_filter=None, parent_id=None):
    svc = get_drive_service()
    pid = parent_id or drive_folder_id
    q = f"'{pid}' in parents and trashed = false"
    if mime_filter:
        q += f" and mimeType contains '{mime_filter}'"
    resp = svc.files().list(q=q, fields="files(id,name,mimeType)").execute()
    return resp.get("files", [])

def download_file(file_id):
    svc = get_drive_service()
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf

def upload_file(name, data, mime_type, parent_id=None):
    svc = get_drive_service()
    pid = parent_id or drive_folder_id
    # see if exists
    existing = svc.files().list(
        q=f"name='{name}' and '{pid}' in parents",
        fields="files(id)"
    ).execute().get("files", [])
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type)
    if existing:
        return svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        meta = {"name": name, "parents": [pid]}
        return svc.files().create(body=meta, media_body=media).execute()

def find_folder(name, parent_id=None):
    svc = get_drive_service()
    pid = parent_id or drive_folder_id
    q = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{pid}' in parents and trashed=false"
    )
    resp = svc.files().list(q=q, fields="files(id)").execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None

def create_folder(name, parent_id=None):
    svc = get_drive_service()
    pid = parent_id or drive_folder_id
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [pid],
    }
    return svc.files().create(body=meta, fields="id").execute()["id"]

def find_or_create_folder(name, parent_id=None):
    fid = find_folder(name, parent_id)
    return fid if fid else create_folder(name, parent_id)
