"""Source connectors for the Import page.

Acquire raw EHR file bytes from a cloud account and hand them to the ingest
layer. Two providers, one uniform module surface (see ``base.py``):

  - :mod:`ui.integrations.gdrive`             — Google Drive (OAuth 2.0)
  - :mod:`ui.integrations.dropbox_connector`  — Dropbox (OAuth 2.0)

``CONNECTORS`` lets the page iterate providers by display name without caring
which SDK backs each one. Computer upload needs no connector — Streamlit's
``st.file_uploader`` already yields the bytes directly.
"""

from __future__ import annotations

from ui.integrations import dropbox_connector, gdrive
from ui.integrations.base import ConnectorError, RemoteFile

# Display name -> connector module. Ordered as shown in the UI.
CONNECTORS = {
    gdrive.NAME: gdrive,
    dropbox_connector.NAME: dropbox_connector,
}

__all__ = ["CONNECTORS", "ConnectorError", "RemoteFile"]
