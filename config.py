# config.py
import os
import json
from dataclasses import dataclass
from typing import Optional, Dict

import streamlit as st

@dataclass
class OAuthConfig:
    client_id: str
    client_secret: str
    refresh_token: str

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
    logo_path: str
    fonts_zip_path: str

def load_config() -> AppConfig:
    secrets = st.secrets  # reads .streamlit/secrets.toml

    openai_api_key  = secrets["OPENAI_API_KEY"]
    drive_folder_id = secrets["DRIVE_FOLDER_ID"]

    oauth_cfg = None
    if "oauth_manual" in secrets:
        om = secrets["oauth_manual"]
        oauth_cfg = OAuthConfig(
            client_id     = om["client_id"],
            client_secret = om["client_secret"],
            refresh_token = om["refresh_token"],
        )

    sa_cfg = None
    if "drive_service_account" in secrets:
        sa = secrets["drive_service_account"]
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

    # static asset paths can also live in secrets or env
    logo_path     = secrets.get("LOGO_PATH", "updated_logo.png")
    fonts_zip     = secrets.get("FONTS_ZIP_PATH", "Poppins.zip")

    return AppConfig(
        openai_api_key  = openai_api_key,
        drive_folder_id = drive_folder_id,
        oauth           = oauth_cfg,
        service_account = sa_cfg,
        logo_path       = logo_path,
        fonts_zip_path  = fonts_zip,
    )
