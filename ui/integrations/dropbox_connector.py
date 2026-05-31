"""Dropbox connector — OAuth 2.0 via the SDK's ``DropboxOAuth2Flow``.

Lazy-imports the ``dropbox`` SDK so the app still runs without the optional
``integrations`` extra; when it's missing :func:`sdk_available` is False and the
page shows install guidance.

The SDK's flow needs a mutable session mapping that survives the redirect — we
hand it a dedicated dict kept in ``st.session_state`` (which persists across
Streamlit reruns within the browser session). The access token is held in
session state only; nothing is written to disk.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.integrations import _store, config
from ui.integrations.base import ConnectorError, RemoteFile

NAME = "Dropbox"
_TOKEN_KEY = "dropbox_token"
_CSRF_KEY = "dropbox-auth-csrf-token"


def configured() -> bool:
    return config.dropbox_configured()


def sdk_available() -> bool:
    try:
        import dropbox  # noqa: F401
    except ImportError:
        return False
    return True


def connected() -> bool:
    return _TOKEN_KEY in st.session_state


def setup_help() -> str:
    return (
        "**Connect Dropbox**\n\n"
        "1. In the [Dropbox App Console](https://www.dropbox.com/developers/apps), "
        "create an app with **scoped access** and the `files.content.read` + "
        "`files.metadata.read` permissions.\n"
        f"2. Add `{config.redirect_uri()}` as an OAuth 2 redirect URI.\n"
        "3. Put the app key/secret in `.streamlit/secrets.toml` under "
        "`[dropbox]` (see `secrets.toml.example`).\n"
        "4. `pip install -e '.[integrations]'` to install the Dropbox SDK."
    )


def _flow(session: dict[str, Any]) -> Any:
    import dropbox

    cfg = config.dropbox()
    return dropbox.DropboxOAuth2Flow(
        consumer_key=cfg["app_key"],
        consumer_secret=cfg["app_secret"],
        redirect_uri=config.redirect_uri(),
        session=session,
        csrf_token_session_key=_CSRF_KEY,
        token_access_type="offline",
    )


def auth_url() -> str:
    """Start the flow and persist its CSRF session so the callback can finish.

    Dropbox validates the returned ``state`` against the CSRF token it stored in
    the flow session. The redirect starts a fresh Streamlit session, so we park
    that session in the process-global store keyed by the CSRF token (which is
    exactly what comes back as ``state``).
    """
    session: dict[str, Any] = {}
    url = _flow(session).start()
    csrf = session[_CSRF_KEY]
    _store.remember(csrf, NAME, session)
    return str(url)


def complete_auth(query_params: dict[str, Any]) -> None:
    """Validate the callback and store the resulting access token."""
    if "code" not in query_params:
        raise ConnectorError("No authorization code in the callback URL.")
    state = query_params.get("state", "")
    csrf = state.split("|", 1)[0]
    record = _store.recall(csrf)
    session = record["session"] if record else {}
    try:
        result = _flow(session).finish(query_params)
    except Exception as err:
        raise ConnectorError(f"Dropbox auth failed: {err}") from err
    st.session_state[_TOKEN_KEY] = result.access_token
    _store.forget(csrf)


def disconnect() -> None:
    st.session_state.pop(_TOKEN_KEY, None)


def _client() -> Any:
    import dropbox

    return dropbox.Dropbox(st.session_state[_TOKEN_KEY])


def list_files() -> list[RemoteFile]:
    """List files in the account root (one level, files only)."""
    import dropbox

    try:
        result = _client().files_list_folder("")
    except Exception as err:
        raise ConnectorError(f"Could not list Dropbox files: {err}") from err
    return [
        RemoteFile(id=entry.path_lower, name=entry.name)
        for entry in result.entries
        if isinstance(entry, dropbox.files.FileMetadata)
    ]


def fetch(file_id: str, name: str) -> Any:
    """Download one file's raw bytes as an ingest ``UploadedFile``."""
    from ingest import UploadedFile

    try:
        _meta, resp = _client().files_download(file_id)
    except Exception as err:
        raise ConnectorError(f"Could not download {name!r}: {err}") from err
    return UploadedFile(name=name, data=resp.content)
