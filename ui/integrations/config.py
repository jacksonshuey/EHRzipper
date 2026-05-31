"""OAuth configuration, read from Streamlit secrets.

Client IDs/secrets and the redirect URI come from ``.streamlit/secrets.toml``
(git-ignored). Nothing is hard-coded and nothing falls back to a real
credential — an unconfigured connector simply reports itself unconfigured and
the page shows setup instructions instead of a broken button.

Expected secrets.toml shape (see secrets.toml.example):

    [oauth]
    redirect_uri = "http://localhost:8501"

    [google_drive]
    client_id = "..."
    client_secret = "..."

    [dropbox]
    app_key = "..."
    app_secret = "..."
"""

from __future__ import annotations

from typing import Any

import streamlit as st

_DEFAULT_REDIRECT = "http://localhost:8501"


def _section(name: str) -> dict[str, Any]:
    """Return a secrets section as a plain dict, or {} if absent."""
    try:
        return dict(st.secrets[name])
    except Exception:
        return {}


def redirect_uri() -> str:
    """The OAuth redirect URI.

    Must exactly match a redirect URI registered in each provider's app
    console. Both connectors share one URI — the page tracks which provider a
    callback belongs to via session state.
    """
    return str(_section("oauth").get("redirect_uri", _DEFAULT_REDIRECT))


def google_drive() -> dict[str, Any]:
    return _section("google_drive")


def dropbox() -> dict[str, Any]:
    return _section("dropbox")


def google_drive_configured() -> bool:
    cfg = google_drive()
    return bool(cfg.get("client_id") and cfg.get("client_secret"))


def dropbox_configured() -> bool:
    cfg = dropbox()
    return bool(cfg.get("app_key") and cfg.get("app_secret"))
