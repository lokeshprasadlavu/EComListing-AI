from google.oauth2 import service_account
from googleapiclient.discovery import build
from shared.config import OAuthConfig, ServiceAccountConfig

# Drive setup
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

def init_drive_service(
    oauth_cfg: OAuthConfig = None,
    sa_cfg:   ServiceAccountConfig = None
):
    """
    Returns a Google Drive v3 service client.
    - If oauth_cfg is provided: use OAuth flow with refresh token.
    - Else if sa_cfg is provided: use service account.
    """
    if oauth_cfg:
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=None,
            refresh_token=oauth_cfg.refresh_token,
            token_uri=oauth_cfg.token_uri,
            client_id=oauth_cfg.client_id,
            client_secret=oauth_cfg.client_secret
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)

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
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    raise ValueError("Must provide either OAuthConfig or ServiceAccountConfig to init drive.")
