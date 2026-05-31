"""
Per-patient abstraction pipeline.

Reads every `.txt` note under a patient's notes dir, runs the abstractor on
each, and returns one `AbstractionResult` per note.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from abstraction.types import AbstractionResult

# Maps note filename stems (from synthetic/notes.py) to canonical note types.
_NOTE_TYPE_MAP = {
    "initial_consult": "consult",
    "consult": "consult",
    "pathology_report": "pathology",
    "pathology": "pathology",
    "radiology_report": "radiology",
    "radiology": "radiology",
    "progress_note": "progress",
    "progress": "progress",
}


class Abstractor(Protocol):
    """Structural type satisfied by NoteAbstractor and RuleBasedAbstractor."""

    async def abstract(
        self,
        note_text: str,
        *,
        patient_id: str,
        note_type: str,
        note_path: str | None = ...,
    ) -> AbstractionResult: ...


def infer_note_type(note_path: Path) -> str:
    """Infer canonical note type from a note file path."""
    stem = note_path.stem.lower()
    if stem in _NOTE_TYPE_MAP:
        return _NOTE_TYPE_MAP[stem]
    for key, value in _NOTE_TYPE_MAP.items():
        if key in stem:
            return value
    return "unknown"


async def abstract_patient_notes(
    patient_id: str,
    notes_dir: Path,
    abstractor: Abstractor,
) -> list[AbstractionResult]:
    """Run the abstractor over every `.txt` note in `notes_dir`.

    Notes are processed in sorted filename order for determinism.
    """
    results: list[AbstractionResult] = []
    if not notes_dir.exists():
        return results

    for note_path in sorted(notes_dir.glob("*.txt")):
        text = note_path.read_text(encoding="utf-8")
        if not text.strip():
            continue
        note_type = infer_note_type(note_path)
        result = await abstractor.abstract(
            text,
            patient_id=patient_id,
            note_type=note_type,
            note_path=str(note_path),
        )
        results.append(result)
    return results
