"""
EHRzipper type system — healthcare extensions layered on the generic zipper core.

zipper ships the seven universal data types and the canonical row models. This
module re-exports those models unchanged and adds two healthcare-specific
subclasses:

  - ``GlobalCanonicalColumn`` gains declared clinical properties
    (canonical_unit, controlled_vocabulary, analyte, code_system). Seeded as
    global rows, these form the *data dictionary* the EHRNormalizer reads at
    normalize time to convert units and validate coded values.
  - ``IngestRow`` defaults ``workspace_key`` to ``"ehrzipper-default"``.

``ZipperingDataType`` below documents the ten types this project uses (the seven
zipper base types plus partial_date / quantity_with_unit / coded_value). It is
documentation only — the row models type ``data_type`` as open ``str`` (see
zipper.types) so domain types need no core fork.
"""

from __future__ import annotations

from typing import Literal

from zipper.types import GlobalCanonicalColumn as _BaseGlobalCanonicalColumn
from zipper.types import IngestRow as _BaseIngestRow
from zipper.types import (
    IngestValue,
    RoutingVerdict,
    ZipperedSignalRow,
    ZipperingDecisionRow,
    ZipperingSchemaRow,
    ZipperingVerdict,
)

# ---------------------------------------------------------------------------
# Data-type vocabulary (documentation)
# ---------------------------------------------------------------------------

ZipperingDataType = Literal[
    "text",
    "integer",
    "numeric",
    "boolean",
    "timestamp",
    "jsonb",
    "string[]",
    # Healthcare extensions
    "partial_date",
    "quantity_with_unit",
    "coded_value",
]

# Haiku's verdict shape IS the generic router verdict; aliased for back-compat.
HaikuRoutingVerdict = RoutingVerdict


# ---------------------------------------------------------------------------
# Healthcare-extended models
# ---------------------------------------------------------------------------


class GlobalCanonicalColumn(_BaseGlobalCanonicalColumn):
    """Global canonical column + declared clinical properties (the data dictionary).

    When seeded as global rows, these properties travel with the resolved
    canonical target and are read by ``EHRNormalizer`` at normalize time:
      - canonical_unit:        UCUM unit a quantity_with_unit normalizes into
      - controlled_vocabulary: pipe-separated allowed codes for a coded_value
      - analyte:               analyte hint for unit conversion (e.g. "wbc")
      - code_system:           default coding system for a bare-string coded_value
    """

    canonical_unit: str | None = None
    controlled_vocabulary: str | None = None
    analyte: str | None = None
    code_system: str | None = None


class IngestRow(_BaseIngestRow):
    """zipper ``IngestRow`` with the EHRzipper default workspace partition."""

    workspace_key: str = "ehrzipper-default"


__all__ = [
    "GlobalCanonicalColumn",
    "HaikuRoutingVerdict",
    "IngestRow",
    "IngestValue",
    "ZipperedSignalRow",
    "ZipperingDataType",
    "ZipperingDecisionRow",
    "ZipperingSchemaRow",
    "ZipperingVerdict",
]
