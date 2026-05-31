"""Inbound ingestion layer — "how we upload data into the system".

This package is the bridge between a file as a hospital would deliver it
(FHIR R4 Bundle JSON, HL7v2 messages, flat CSV) and the engine's uniform
``IngestRow`` contract. The UI source connectors (computer upload, Google
Drive, Dropbox) hand raw bytes to :func:`ingest.runner.run_ingest`, which
detects the format, parses it into ``IngestRow`` objects, and runs them
through the three-tier reconciliation engine.

It deliberately depends only on the engine package (``ehrzipper``), never on
the UI — so the same path is exercisable from a notebook, a test, or Streamlit.
"""

from ingest.types import IngestReport, UploadedFile

__all__ = ["IngestReport", "UploadedFile"]
