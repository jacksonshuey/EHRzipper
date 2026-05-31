"""
Haiku column-routing assessor — re-exported from zipper.

The LLM routing tier lives in zipper now (same model id, forced tool_choice,
temperature 0, strict input_schema, 8s timeout). EHRzipper consumes it unchanged;
this module re-exports the symbols so existing imports
(``from ehrzipper.haiku_router import AssessInputs, HaikuRouter``) keep working.
"""

from __future__ import annotations

from zipper.config import DEFAULT_MODEL, DEFAULT_TIMEOUT_MS
from zipper.router import (
    AssessInputs,
    HaikuRouter,
    _parse_verdict,
    assess_column_routing,
)

# Back-compat aliases for the previous module-level constants.
HAIKU_MODEL = DEFAULT_MODEL
HAIKU_TIMEOUT_MS = DEFAULT_TIMEOUT_MS

__all__ = [
    "HAIKU_MODEL",
    "HAIKU_TIMEOUT_MS",
    "AssessInputs",
    "HaikuRouter",
    "_parse_verdict",
    "assess_column_routing",
]
