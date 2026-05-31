"""
Abstraction layer (P4) — LLM extraction of structured oncology fields from
unstructured clinical notes, plus an eval set that scores accuracy against
ground truth derived from the synthetic PatientProfile objects.

Public surface:
    abstraction.types        AbstractedFields, AbstractionResult
    abstraction.abstractor   NoteAbstractor (LLM), RuleBasedAbstractor (--no-llm)
    abstraction.pipeline     abstract_patient_notes
    abstraction.batch        abstract_cohort
    abstraction.eval         AbstractionEvaluator
"""
