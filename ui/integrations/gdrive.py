"""Google Drive connector — OAuth 2.0 authorization-code flow.

Lazy-imports ``google-auth-oauthlib`` / ``google-api-python-client`` so the app
still runs when the optional ``integrations`` extra isn't installed; in that
case :func:`sdk_available` is False and the page shows install guidance.

Read-only scope (``drive.readonly``) — the demo never writes to the user's
Drive. The access token is held in ``st.session_state`` for the session only.
"""

from __future__ import annotations

import io
import json
from typing import Any

import streamlit as st

from ui.integrations import _store, config
from ui.integrations.base import ConnectorError, RemoteFile

NAME = "Google Drive"
_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_TOKEN_KEY = "gdrive_token"
_STATE_KEY = "gdrive_oauth_state"
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def configured() -> bool:
    return config.google_drive_configured()


def sdk_available() -> bool:
    try:
        import google_auth_oauthlib.flow  # noqa: F401
        import googleapiclient.discovery  # noqa: F401
    except ImportError:
        return False
    return True


def connected() -> bool:
    return _TOKEN_KEY in st.session_state


def setup_help() -> str:
    return (
        "**Connect Google Drive**\n\n"
        "1. In the [Google Cloud Console](https://console.cloud.google.com/), "
        "create an OAuth 2.0 **Web application** client.\n"
        f"2. Add `{config.redirect_uri()}` as an authorized redirect URI.\n"
        "3. Enable the **Google Drive API** for the project.\n"
        "4. Put the client id/secret in `.streamlit/secrets.toml` under "
        "`[google_drive]` (see `secrets.toml.example`).\n"
        "5. `pip install -e '.[integrations]'` to install the Google SDK."
    )


def _client_config() -> dict[str, Any]:
    cfg = config.google_drive()
    return {
        "web": {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": [config.redirect_uri()],
        }
    }


def _flow() -> Any:
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        _client_config(), scopes=_SCOPES, redirect_uri=config.redirect_uri()
    )


def auth_url() -> str:
    """Build the consent URL and record the handshake for the callback."""
    url, state = _flow().authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    st.session_state[_STATE_KEY] = state
    # Survive the redirect (which starts a fresh session) so the callback can
    # tell this code belongs to Google. Token exchange itself needs no state.
    _store.remember(state, NAME)
    return str(url)


def complete_auth(query_params: dict[str, Any]) -> None:
    """Exchange the redirect ``?code=`` for an access token."""
    code = query_params.get("code")
    if not code:
        raise ConnectorError("No authorization code in the callback URL.")
    flow = _flow()
    try:
        flow.fetch_token(code=code)
    except Exception as err:
        raise ConnectorError(f"Token exchange failed: {err}") from err
    creds = flow.credentials
    st.session_state[_TOKEN_KEY] = creds.to_json()
    st.session_state.pop(_STATE_KEY, None)
    state = query_params.get("state")
    if state:
        _store.forget(state)


def disconnect() -> None:
    st.session_state.pop(_TOKEN_KEY, None)
    st.session_state.pop(_STATE_KEY, None)


def _credentials() -> Any:
    from google.oauth2.credentials import Credentials

    return Credentials.from_authorized_user_info(
        json.loads(st.session_state[_TOKEN_KEY]), _SCOPES
    )


def _service() -> Any:
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


def list_files() -> list[RemoteFile]:
    """List non-folder files in the connected account (newest first)."""
    query = "mimeType != 'application/vnd.google-apps.folder' and trashed = false"
    try:
        resp = (
            _service()
            .files()
            .list(
                q=query,
                pageSize=100,
                orderBy="modifiedTime desc",
                fields="files(id, name)",
            )
            .execute()
        )
    except Exception as err:
        raise ConnectorError(f"Could not list Drive files: {err}") from err
    return [RemoteFile(id=f["id"], name=f["name"]) for f in resp.get("files", [])]


def fetch(file_id: str, name: str) -> Any:
    """Download one file's raw bytes as an ingest ``UploadedFile``."""
    from googleapiclient.http import MediaIoBaseDownload

    from ingest import UploadedFile

    buf = io.BytesIO()
    try:
        request = _service().files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    except Exception as err:
        raise ConnectorError(f"Could not download {name!r}: {err}") from err
    return UploadedFile(name=name, data=buf.getvalue())
