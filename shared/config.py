import os
import json
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class OAuthConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    token_uri: str


@dataclass
class ServiceAccountConfig:
    type: str
    project_id: str
    private_key_id: str
    private_key: str
    client_email: str
    client_id: str
    auth_uri: str
    token_uri: str
    auth_provider_x509_cert_url: str
    client_x509_cert_url: str


@dataclass
class AppConfig:
    drive_folder_id: str
    oauth: Optional[OAuthConfig]
    service_account: Optional[ServiceAccountConfig]


def load_config(secrets: Optional[Dict[str, Any]] = None) -> AppConfig:
    """
    Loads configuration either from:
    - Streamlit secrets (as dict), or
    - Environment variables (when secrets is None)
    Supports both OAuth and Service Account credentials.
    """
    source = secrets or os.environ
    def get(key: str, default=None):
        return source.get(key, default)
    drive_folder_id = get("DRIVE_FOLDER_ID")
    if  not drive_folder_id:
        raise ValueError("Missing DRIVE_FOLDER_ID in config.")

    # ─── OAuth Config ───
    oauth_cfg = None
    oauth_keys = ["client_id", "client_secret", "refresh_token"]
    if all(get(k) for k in oauth_keys):
        oauth_cfg = OAuthConfig(
            client_id     = get("client_id"),
            client_secret = get("client_secret"),
            refresh_token = get("refresh_token"),
            token_uri     = get("token_uri", "https://oauth2.googleapis.com/token")
        )

    # ─── Service Account Config ───
    sa_cfg = None
    sa = None

    if "drive_service_account" in source:
        sa = source["drive_service_account"]
    elif get("DRIVE_SERVICE_ACCOUNT_JSON"):
        try:
            sa = json.loads(get("DRIVE_SERVICE_ACCOUNT_JSON"))
        except Exception as e:
            raise ValueError(f"Failed to parse DRIVE_SERVICE_ACCOUNT_JSON: {e}")

    if sa:
        sa_cfg = ServiceAccountConfig(
            type                          = sa["type"],
            project_id                    = sa["project_id"],
            private_key_id                = sa["private_key_id"],
            private_key                   = sa["private_key"],
            client_email                  = sa["client_email"],
            client_id                     = sa["client_id"],
            auth_uri                      = sa["auth_uri"],
            token_uri                     = sa["token_uri"],
            auth_provider_x509_cert_url   = sa["auth_provider_x509_cert_url"],
            client_x509_cert_url          = sa["client_x509_cert_url"],
        )

    return AppConfig(
        drive_folder_id = drive_folder_id,
        oauth           = oauth_cfg,
        service_account = sa_cfg
    )
