import os
import json
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union


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
    openai_api_key: str
    drive_folder_id: str
    oauth: Optional[OAuthConfig]
    service_account: Optional[ServiceAccountConfig]


def load_config(secrets: Optional[Dict[str, Any]] = None) -> AppConfig:
    """
    Loads configuration either from:
    - Streamlit secrets (as dict), or
    - Environment variables (when secrets is None)
    """
    source = secrets or os.environ

    def get(key: str, default=None):
        return source.get(key, default)

    # Required keys
    openai_api_key = get("OPENAI_API_KEY")
    drive_folder_id = get("DRIVE_FOLDER_ID")
    if not openai_api_key or not drive_folder_id:
        raise ValueError("Missing OPENAI_API_KEY or DRIVE_FOLDER_ID in config.")

    # OAuth config
    oauth_cfg = None
    if "oauth" in source:
        o = source["oauth"]
    elif get("OAUTH_CLIENT_ID"):
        o = {
            "client_id":     get("OAUTH_CLIENT_ID"),
            "client_secret": get("OAUTH_CLIENT_SECRET"),
            "refresh_token": get("OAUTH_REFRESH_TOKEN"),
            "token_uri":     get("OAUTH_TOKEN_URI", "https://oauth2.googleapis.com/token")
        }
    else:
        o = None

    if o:
        oauth_cfg = OAuthConfig(
            client_id     = o["client_id"],
            client_secret = o["client_secret"],
            refresh_token = o["refresh_token"],
            token_uri     = o["token_uri"]
        )

    # Service Account config
    sa_cfg = None
    if "drive_service_account" in source:
        sa = source["drive_service_account"]
    elif get("DRIVE_SERVICE_ACCOUNT_JSON"):
        try:
            sa = json.loads(get("DRIVE_SERVICE_ACCOUNT_JSON"))
        except Exception as e:
            raise ValueError(f"Failed to parse DRIVE_SERVICE_ACCOUNT_JSON: {e}")
    else:
        sa = None

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
        openai_api_key  = openai_api_key,
        drive_folder_id = drive_folder_id,
        oauth           = oauth_cfg,
        service_account = sa_cfg
    )
