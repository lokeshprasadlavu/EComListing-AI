from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def upload_video_to_youtube(
    video_file: str,
    title: str,
    description: str,
    keywords: str,
    categoryId: str,
    privacyStatus: str
) -> str:
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "client_secrets.json")
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_console()
    yt = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": keywords.split(","),
            "categoryId": categoryId
        },
        "status": {"privacyStatus": privacyStatus}
    }
    req = yt.videos().insert(part="snippet,status", body=body, media_body=video_file)
    resp = req.execute()
    return f"https://youtu.be/{resp['id']}"
