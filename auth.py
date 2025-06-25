# auth.py
import os
import openai
from typing import Union
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

from config import OAuthConfig, ServiceAccountConfig

# OpenAI setup
def get_openai_client(api_key: str):
    os.environ["OPENAI_API_KEY"] = api_key
    openai.api_key = api_key
    return openai

# Drive setup
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

def init_drive_service(
    oauth_cfg: OAuthConfig = None,
    sa_cfg:   ServiceAccountConfig = None
):
    """
    Returns a Google Drive v3 service client.
    - If sa_cfg is provided: use service-account.
    - Else if oauth_cfg is provided: run or reuse OAuth refresh flow.
    """
    if sa_cfg:
        creds = service_account.Credentials.from_service_account_info(
            {
                "type":                        sa_cfg.type,
                "project_id":                  sa_cfg.project_id,
                "private_key_id":              sa_cfg.private_key_id,
                "private_key":                 sa_cfg.private_key,
                "client_email":                sa_cfg.client_email,
                "client_id":                   sa_cfg.client_id,
                "auth_uri":                    sa_cfg.auth_uri,
                "token_uri":                   sa_cfg.token_uri,
                "auth_provider_x509_cert_url": sa_cfg.auth_provider_x509_cert_url,
                "client_x509_cert_url":        sa_cfg.client_x509_cert_url,
            },
            scopes=DRIVE_SCOPES
        )
        return build("drive", "v3", credentials=creds)

    if oauth_cfg:
        token_path = ".streamlit/drive_token.pickle"
        creds = None
        # load existing token if present
        if os.path.exists(token_path):
            import pickle
            with open(token_path, "rb") as f:
                creds = pickle.load(f)

        # refresh or request new
        if creds and creds.valid:
            pass
        elif creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id":     oauth_cfg.client_id,
                        "client_secret": oauth_cfg.client_secret,
                        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"],
                        "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                        "token_uri":     "https://oauth2.googleapis.com/token",
                    }
                },
                scopes=DRIVE_SCOPES,
            )
            creds = flow.run_console()
            # persist for next run
            import pickle
            os.makedirs(os.path.dirname(token_path), exist_ok=True)
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)

        return build("drive", "v3", credentials=creds)

    raise ValueError("Must provide either OAuthConfig or ServiceAccountConfig to init drive.")

