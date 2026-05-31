"""
Note abstractor — extracts structured fields from one clinical note.

Two implementations:
  - `NoteAbstractor`     LLM-backed. claude-haiku-4-5, temperature 0, forced
                         tool_choice on the `extract_fields` tool whose schema
                         mirrors `AbstractedFields`. Retries (3 attempts,
                         exponential backoff) on transient API errors. Logs
                         token usage per call.
  - `RuleBasedAbstractor`  Deterministic regex extractor used by the
                         `--no-llm` CLI path and by tests; no network, no key.

Both expose the same surface:
    async def abstract(note_text, *, patient_id, note_type, note_path) -> AbstractionResult

so `pipeline.py` / `batch.py` are agnostic to which one they were given.

LLM-call conventions follow CLAUDE.md / ehrzipper/haiku_router.py:
forced tool_choice, strict input_schema, temperature 0, timeout.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, cast

import anthropic

from abstraction.types import AbstractedFields, AbstractionResult, ConfidenceLevel

logger = logging.getLogger("abstraction.abstractor")

ABSTRACTION_MODEL = "claude-haiku-4-5"

# Per-call abort budget (ms).
ABSTRACTION_TIMEOUT_MS = 30_000

# Retry policy for transient API failures.
MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 0.5

SYSTEM_PROMPT = (
    "You are a clinical data abstractor for an oncology real-world-evidence "
    "(RWE) pipeline. Extract only what is explicitly stated in the note. Do "
    "not infer. If a field is uncertain or not stated, leave it null (None) "
    "and add its name to uncertain_fields. Normalize biomarker statuses to one "
    "of: positive, negative, not_tested, unknown. Normalize PD-L1 status to "
    "high, low, or negative. Use lowercase snake_case for histology and "
    "metastatic site names. Dates must be ISO format (YYYY-MM-DD)."
)

# ---------------------------------------------------------------------------
# Tool schema — mirrors AbstractedFields field-for-field.
# ---------------------------------------------------------------------------

_EXTRACT_TOOL: dict[str, Any] = {
    "name": "extract_fields",
    "description": (
        "Record the structured oncology fields explicitly stated in this "
        "clinical note. Leave fields null when not stated."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "histology": {"type": ["string", "null"]},
            "stage": {"type": ["string", "null"]},
            "egfr_status": {"type": ["string", "null"]},
            "egfr_mutation": {"type": ["string", "null"]},
            "alk_status": {"type": ["string", "null"]},
            "ros1_status": {"type": ["string", "null"]},
            "kras_status": {"type": ["string", "null"]},
            "kras_variant": {"type": ["string", "null"]},
            "braf_status": {"type": ["string", "null"]},
            "pdl1_status": {"type": ["string", "null"]},
            "pdl1_tps": {"type": ["number", "null"]},
            "ecog": {"type": ["integer", "null"]},
            "progression_mentioned": {"type": "boolean"},
            "progression_date": {"type": ["string", "null"]},
            "new_metastatic_sites": {
                "type": "array",
                "items": {"type": "string"},
            },
            "treatments_mentioned": {
                "type": "array",
                "items": {"type": "string"},
            },
            "source_note_type": {"type": ["string", "null"]},
            "extraction_confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "uncertain_fields": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "progression_mentioned",
            "new_metastatic_sites",
            "treatments_mentioned",
            "extraction_confidence",
            "uncertain_fields",
        ],
    },
}


def _build_user_prompt(note_text: str, note_type: str) -> str:
    return (
        f"Note type: {note_type}\n\n"
        "Extract the structured oncology fields from the following clinical "
        "note. Call the extract_fields tool with your result.\n\n"
        "----- BEGIN NOTE -----\n"
        f"{note_text}\n"
        "----- END NOTE -----"
    )


def _coerce_fields(raw: Any, note_type: str) -> AbstractedFields:
    """Validate Claude's tool_use input into AbstractedFields.

    Drops unknown keys, fills source_note_type when the model omitted it.
    """
    if not isinstance(raw, dict):
        raise RuntimeError(f"extract_fields tool input is not an object: {raw!r}")
    data = dict(raw)
    if not data.get("source_note_type"):
        data["source_note_type"] = note_type
    return AbstractedFields.model_validate(data)


class NoteAbstractor:
    """LLM-backed abstractor. Inject a fake client in tests."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic | None = None,
        model: str = ABSTRACTION_MODEL,
    ) -> None:
        self._client = client or anthropic.AsyncAnthropic()
        self.model = model

    async def abstract(
        self,
        note_text: str,
        *,
        patient_id: str,
        note_type: str,
        note_path: str | None = None,
    ) -> AbstractionResult:
        start = time.perf_counter()
        fields, in_tok, out_tok = await self._call_with_retry(note_text, note_type)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return AbstractionResult(
            patient_id=patient_id,
            note_type=note_type,
            note_path=note_path,
            raw_note=note_text,
            fields=fields,
            model=self.model,
            tokens_used=in_tok + out_tok,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency_ms,
        )

    async def _call_with_retry(
        self, note_text: str, note_type: str
    ) -> tuple[AbstractedFields, int, int]:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return await asyncio.wait_for(
                    self._call_once(note_text, note_type),
                    timeout=ABSTRACTION_TIMEOUT_MS / 1000.0,
                )
            except (
                anthropic.APIStatusError,
                anthropic.APIConnectionError,
                TimeoutError,
            ) as exc:
                last_exc = exc
                if attempt == MAX_ATTEMPTS:
                    break
                backoff = BACKOFF_BASE_S * (2 ** (attempt - 1))
                logger.warning(
                    "abstraction attempt %d/%d failed (%s); retrying in %.2fs",
                    attempt,
                    MAX_ATTEMPTS,
                    type(exc).__name__,
                    backoff,
                )
                await asyncio.sleep(backoff)
        assert last_exc is not None
        raise last_exc

    async def _call_once(
        self, note_text: str, note_type: str
    ) -> tuple[AbstractedFields, int, int]:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            temperature=0,
            system=SYSTEM_PROMPT,
            tools=cast("list[anthropic.types.ToolParam]", [_EXTRACT_TOOL]),
            tool_choice=cast(
                "anthropic.types.ToolChoiceToolParam",
                {"type": "tool", "name": _EXTRACT_TOOL["name"]},
            ),
            messages=[
                {"role": "user", "content": _build_user_prompt(note_text, note_type)}
            ],
        )

        tool_use = next(
            (
                block
                for block in response.content
                if getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == _EXTRACT_TOOL["name"]
            ),
            None,
        )
        if tool_use is None:
            raise RuntimeError("Claude returned no extract_fields tool_use block")

        in_tok = 0
        out_tok = 0
        usage = getattr(response, "usage", None)
        if usage is not None:
            in_tok = int(getattr(usage, "input_tokens", 0) or 0)
            out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        logger.info(
            "abstraction call: model=%s in_tokens=%d out_tokens=%d",
            self.model,
            in_tok,
            out_tok,
        )

        fields = _coerce_fields(getattr(tool_use, "input", None), note_type)
        return fields, in_tok, out_tok


# ---------------------------------------------------------------------------
# Rule-based abstractor (--no-llm). Deterministic, offline, used for testing.
# ---------------------------------------------------------------------------

_HISTOLOGIES = [
    "adenosquamous_carcinoma",
    "squamous_cell_carcinoma",
    "large_cell_carcinoma",
    "sarcomatoid_carcinoma",
    "adenocarcinoma",
    "nsclc_nos",
]

_TREATMENT_VOCAB = [
    "osimertinib",
    "alectinib",
    "lorlatinib",
    "entrectinib",
    "crizotinib",
    "sotorasib",
    "adagrasib",
    "pembrolizumab",
    "nivolumab",
    "carboplatin",
    "cisplatin",
    "pemetrexed",
    "paclitaxel",
    "nab-paclitaxel",
    "docetaxel",
    "gemcitabine",
    "bevacizumab",
]

_SITE_VOCAB = [
    "brain",
    "bone",
    "liver",
    "adrenal",
    "lung_contralateral",
    "lymph_node_distant",
]

_BIOMARKER_RE = re.compile(
    r"\b(EGFR|ALK|ROS1|KRAS|BRAF)\b\s*:?\s*(positive|negative|not[ _]tested|unknown)",
    re.IGNORECASE,
)
_STAGE_RE = re.compile(r"\bstage\s+(IV[AB]|III[BC])\b", re.IGNORECASE)
_ECOG_RE = re.compile(r"ECOG[^0-9]{0,30}?([0-4])", re.IGNORECASE)
_PDL1_RE = re.compile(r"PD-?L1\s*:?\s*(high|low|negative)", re.IGNORECASE)
_TPS_RE = re.compile(r"TPS\s*([0-9]+(?:\.[0-9]+)?)\s*%?", re.IGNORECASE)
_PROG_DATE_RE = re.compile(
    r"progression\s+(?:documented|identified)?[^0-9]{0,40}?(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


class RuleBasedAbstractor:
    """Regex extractor matching the synthetic template note format.

    Same async surface as NoteAbstractor so the pipeline can use either.
    """

    model = "rule-based-v1"

    async def abstract(
        self,
        note_text: str,
        *,
        patient_id: str,
        note_type: str,
        note_path: str | None = None,
    ) -> AbstractionResult:
        fields = self.extract(note_text, note_type)
        return AbstractionResult(
            patient_id=patient_id,
            note_type=note_type,
            note_path=note_path,
            raw_note=note_text,
            fields=fields,
            model=self.model,
        )

    def extract(self, note_text: str, note_type: str) -> AbstractedFields:
        lower = note_text.lower()
        uncertain: list[str] = []

        # Stage
        stage_m = _STAGE_RE.search(note_text)
        stage = stage_m.group(1).upper() if stage_m else None

        # Histology — first vocab match (longest first to prefer specific).
        histology: str | None = None
        for h in _HISTOLOGIES:
            if h.replace("_", " ") in lower:
                histology = h
                break

        # Biomarkers
        biomarkers: dict[str, str] = {}
        for m in _BIOMARKER_RE.finditer(note_text):
            name = m.group(1).lower()
            status = m.group(2).lower().replace(" ", "_")
            biomarkers[name] = status

        # PD-L1 status + TPS
        pdl1_m = _PDL1_RE.search(note_text)
        pdl1_status = pdl1_m.group(1).lower() if pdl1_m else None
        tps_m = _TPS_RE.search(note_text)
        pdl1_tps = float(tps_m.group(1)) if tps_m else None

        # Mutation / variant details
        egfr_mutation: str | None = None
        if "exon 19" in lower or "exon19" in lower:
            egfr_mutation = "exon19_deletion"
        elif "l858r" in lower:
            egfr_mutation = "L858R"
        kras_variant: str | None = None
        kras_var_m = re.search(r"\bG12[A-Z]\b", note_text)
        if kras_var_m:
            kras_variant = kras_var_m.group(0).upper()

        # ECOG
        ecog_m = _ECOG_RE.search(note_text)
        ecog = int(ecog_m.group(1)) if ecog_m else None

        # Progression
        prog_mentioned = "progression" in lower
        prog_date_m = _PROG_DATE_RE.search(note_text)
        progression_date = prog_date_m.group(1) if prog_date_m else None

        # Metastatic sites — only when progression / involvement mentioned.
        sites: list[str] = []
        if "new involvement at" in lower or prog_mentioned:
            for site in _SITE_VOCAB:
                if site in lower:
                    sites.append(site)

        # Treatments
        treatments: list[str] = []
        for drug in _TREATMENT_VOCAB:
            if drug in lower and drug not in treatments:
                treatments.append(drug)

        # Confidence: how many anchor fields did we find?
        anchors = [stage, histology, ecog, pdl1_status]
        found = sum(1 for a in anchors if a is not None)
        confidence: ConfidenceLevel
        if found >= 3:
            confidence = "high"
        elif found >= 1:
            confidence = "medium"
        else:
            confidence = "low"

        for label, val in (("stage", stage), ("histology", histology)):
            if val is None:
                uncertain.append(label)

        return AbstractedFields(
            histology=histology,
            stage=stage,
            egfr_status=biomarkers.get("egfr"),
            egfr_mutation=egfr_mutation,
            alk_status=biomarkers.get("alk"),
            ros1_status=biomarkers.get("ros1"),
            kras_status=biomarkers.get("kras"),
            kras_variant=kras_variant,
            braf_status=biomarkers.get("braf"),
            pdl1_status=pdl1_status,
            pdl1_tps=pdl1_tps,
            ecog=ecog,
            progression_mentioned=prog_mentioned,
            progression_date=progression_date,
            new_metastatic_sites=sites,
            treatments_mentioned=treatments,
            source_note_type=note_type,
            extraction_confidence=confidence,
            uncertain_fields=uncertain,
        )
