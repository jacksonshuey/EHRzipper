"""Shared types and helpers for the source connectors.

A *connector* acquires raw file bytes from one place — the user's computer,
Google Drive, or Dropbox — and hands them to the ingest layer as
``UploadedFile`` objects. The cloud connectors share the same small surface so
the Import page can treat them uniformly:

    configured()                  -> is the OAuth app set up in secrets?
    sdk_available()               -> is the optional SDK installed?
    connected()                   -> do we hold a token this session?
    auth_url()                    -> URL to send the user to for consent
    complete_auth(query_params)   -> exchange the redirect ?code= for a token
    list_files()                  -> browse the account's files
    fetch(file_id, name)          -> download one file's bytes
    disconnect()                  -> drop the session token
    setup_help()                  -> Markdown telling the user how to configure

Tokens live in ``st.session_state`` only — nothing is written to disk, so a
browser refresh that clears session state also clears the credential.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteFile:
    """A file listed in a connected cloud account."""

    id: str
    name: str


class ConnectorError(RuntimeError):
    """Raised when a connector cannot complete an operation (auth, fetch...)."""
