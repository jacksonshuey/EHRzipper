"""Process-global store for in-flight OAuth handshakes.

An OAuth redirect navigates the browser away and back, which starts a fresh
Streamlit session — so ``st.session_state`` set before the redirect is gone by
the time the callback runs. The transient handshake data (which provider, and
Dropbox's CSRF/flow session) must therefore outlive a single session.

``st.cache_resource`` returns one shared object per *server process*, so we key
it by the ``state`` value the provider echoes back in the callback URL. That
lets the callback recover the originating handshake even on a brand-new
session.

Only short-lived handshake tokens live here — never PHI, and never the
long-lived access token (that stays in per-session ``st.session_state``).
"""

from __future__ import annotations

from typing import Any

import streamlit as st


@st.cache_resource
def _pending() -> dict[str, dict[str, Any]]:
    return {}


def remember(
    state: str, provider: str, session: dict[str, Any] | None = None
) -> None:
    """Record an in-flight handshake, keyed by the OAuth ``state`` token."""
    _pending()[state] = {"provider": provider, "session": session or {}}


def recall(state: str) -> dict[str, Any] | None:
    return _pending().get(state)


def provider_for(state: str) -> str | None:
    rec = _pending().get(state)
    return rec["provider"] if rec else None


def forget(state: str) -> None:
    _pending().pop(state, None)
