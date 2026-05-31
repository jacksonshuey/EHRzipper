"""
EHRNormalizer — the healthcare value-normalization seam injected into zipper.

zipper's engine resolves the canonical target for each incoming column, then
calls the injected Normalizer to coerce the value to the canonical type. This
implementation reads the declared clinical properties (canonical_unit,
controlled_vocabulary, analyte, code_system) off the resolved target — which is
why those properties are seeded as GLOBAL canonical columns: globals are the
stable data dictionary the engine passes back in via ``target_global`` at
normalize time. It then delegates to ``ehrzipper.coercions.normalize``, which
routes quantity_with_unit / coded_value / partial_date through their dedicated
coercers.

Implements the ``zipper.Normalizer`` Protocol; raises ehrzipper
``UnsafeCoercion`` (a subclass of zipper's) on unsafe conversions so the engine
routes them to human review instead of crashing ingest.
"""

from __future__ import annotations

from typing import Any

from zipper.types import GlobalCanonicalColumn, ZipperingSchemaRow

from ehrzipper.coercions import CoercionContext, normalize


class EHRNormalizer:
    """Context-aware normalizer: UCUM unit conversion + controlled-vocabulary coding.

    ``target_global`` is typed as the base zipper ``GlobalCanonicalColumn`` (no
    clinical fields), but at runtime it is the EHRzipper subclass carrying the
    data-dictionary properties — hence ``getattr`` rather than attribute access.
    """

    def normalize(
        self,
        value: Any,
        from_type: str,
        to_type: str,
        *,
        target_schema: ZipperingSchemaRow | None = None,
        target_global: GlobalCanonicalColumn | None = None,
    ) -> Any:
        ctx: CoercionContext = {}
        if target_global is not None:
            canonical_unit = getattr(target_global, "canonical_unit", None)
            if canonical_unit is not None:
                ctx["canonical_unit"] = canonical_unit
            controlled_vocabulary = getattr(
                target_global, "controlled_vocabulary", None
            )
            if controlled_vocabulary is not None:
                ctx["controlled_vocabulary"] = controlled_vocabulary
            analyte = getattr(target_global, "analyte", None)
            if analyte is not None:
                ctx["analyte"] = analyte
            code_system = getattr(target_global, "code_system", None)
            if code_system is not None:
                ctx["code_system"] = code_system
        return normalize(value, from_type, to_type, context=ctx)
