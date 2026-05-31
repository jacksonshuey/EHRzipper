"""
Drug classification for lines-of-therapy derivation.

Maps RxNorm display names (and codes, where helpful) to coarse antineoplastic
classes. The class taxonomy here is intentionally coarser than the canonical
`medication_administration.drug_class` enum (canonical-schema.md §B4): for LoT
labeling we care about "chemo vs IO vs TKI" combinations, not the fine-grained
platinum/taxane/pemetrexed split. The canonical fine-grained class is still
carried through on each event and used as a fallback when a drug name is not in
the curated list below.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Curated oncology drug name → coarse class.
#
# TKIs: small-molecule tyrosine-kinase inhibitors (oral targeted therapy).
# IO:   immune checkpoint inhibitors (PD-1 / PD-L1).
# Chemo: cytotoxic chemotherapy (platinums, taxanes, antifolates, etc.).
# Anti-angiogenic agents (bevacizumab, ramucirumab) are treated as chemo-class
#   backbone partners for labeling but do NOT, on their own, anchor a new line.
# ---------------------------------------------------------------------------

TKI_DRUGS: frozenset[str] = frozenset(
    {
        "osimertinib",
        "gefitinib",
        "erlotinib",
        "afatinib",
        "dacomitinib",
        "alectinib",
        "lorlatinib",
        "crizotinib",
        "ceritinib",
        "brigatinib",
        "entrectinib",
        "sotorasib",
        "adagrasib",
        "selpercatinib",
        "capmatinib",
        "tepotinib",
        "dabrafenib",
        "trametinib",
    }
)

IO_DRUGS: frozenset[str] = frozenset(
    {
        "pembrolizumab",
        "nivolumab",
        "atezolizumab",
        "durvalumab",
        "cemiplimab",
        "ipilimumab",
        "tremelimumab",
    }
)

CHEMO_DRUGS: frozenset[str] = frozenset(
    {
        "carboplatin",
        "cisplatin",
        "pemetrexed",
        "paclitaxel",
        "nab-paclitaxel",
        "docetaxel",
        "gemcitabine",
        "vinorelbine",
        "etoposide",
        "bevacizumab",
        "ramucirumab",
    }
)

# Union of everything we recognize as an antineoplastic agent. Used by the
# validator to flag drugs that should not be appearing in a LoT regimen.
ONCOLOGY_DRUGS: frozenset[str] = TKI_DRUGS | IO_DRUGS | CHEMO_DRUGS


def normalize_drug_name(name: str) -> str:
    """Lower-case + strip; tolerant of casing/whitespace drift across sources."""
    return name.strip().lower()


def classify_drug(name: str, fallback_canonical_class: str | None = None) -> str:
    """
    Classify a single drug into {"tki", "io", "chemo"}.

    Falls back to the canonical fine-grained `drug_class` string (e.g.
    "io_pd1", "tki_egfr", "chemotherapy_platinum") when the name is unknown,
    so reconciled events that carry a class but an unfamiliar display still
    classify correctly.
    """
    n = normalize_drug_name(name)
    if n in TKI_DRUGS:
        return "tki"
    if n in IO_DRUGS:
        return "io"
    if n in CHEMO_DRUGS:
        return "chemo"

    # Fallback: lean on the canonical drug_class prefix.
    if fallback_canonical_class:
        c = fallback_canonical_class.lower()
        if c.startswith("tki"):
            return "tki"
        if c.startswith("io"):
            return "io"
        if c.startswith("chemo") or c in {"antiangiogenic"}:
            return "chemo"
    # Unknown → treat as chemo (conservative: still counts as antineoplastic).
    return "chemo"


def regimen_drug_class(
    drugs: list[str], canonical_classes: list[str | None] | None = None
) -> str:
    """
    Derive the combined drug class for a regimen.

    Returns one of: "chemo", "io", "tki", "chemo+io", "tki+io", "tki+chemo".
    Order within combination labels is stable for deterministic output.
    """
    classes: list[str | None] = canonical_classes or [None] * len(drugs)
    present: set[str] = set()
    for drug, canon in zip(drugs, classes, strict=False):
        present.add(classify_drug(drug, canon))

    has_tki = "tki" in present
    has_io = "io" in present
    has_chemo = "chemo" in present

    if has_tki and has_io:
        return "tki+io"
    if has_tki and has_chemo:
        return "tki+chemo"
    if has_chemo and has_io:
        return "chemo+io"
    if has_tki:
        return "tki"
    if has_io:
        return "io"
    return "chemo"
