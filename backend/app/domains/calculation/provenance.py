"""
Numeric provenance model — Phase 2 of the governed calculation architecture
(see docs/calculation_architecture.md).

A single canonical record shape for "where did this number come from,"
built from whichever engine actually produced it (expression evaluator,
formula registry, or the PolicyEngine wrapper), so
massarius/answer_validator.py's provenance-aware check has exactly one
shape to verify against regardless of which engine ran.

This module does not decide whether a claim in an answer is *supported* —
that is answer_validator.py's job (it also has to check literal
retrieved_fact / user_provided_input matches, which have no engine record at
all). This module only builds and stores the records for whichever
calculations actually ran during a request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

PROVENANCE_TYPES = frozenset({
    "retrieved_fact",
    "user_provided_input",
    "policy_engine_result",
    "named_formula_result",
    "expression_derived",
    "presentation_only",
})


@dataclass(frozen=True)
class ProvenanceRecord:
    provenance_id: str        # the engine's own calculation_id — the join key
    provenance_type: str      # one of PROVENANCE_TYPES
    engine: str
    engine_version: str
    numeric_value: str        # canonical Decimal-as-string, for exact/normalized matching
    unit: str
    status: str                # verified | error | missing_input | invalid_input
    source_ref: str = ""       # formula_id / expression text / policyengine variable name

    def normalized_value(self) -> Optional[Decimal]:
        try:
            return Decimal(self.numeric_value)
        except (InvalidOperation, TypeError):
            return None


@dataclass
class ProvenanceStore:
    """Per-request collection of provenance records — built once during
    composition (as each calculation engine runs) and passed into
    validate_answer() so Checkpoint C can look up whether a claimed figure
    traces back to a real, executed calculation."""

    records: dict = field(default_factory=dict)  # provenance_id -> ProvenanceRecord

    def add(self, record: ProvenanceRecord) -> None:
        self.records[record.provenance_id] = record

    def get(self, provenance_id: str) -> Optional[ProvenanceRecord]:
        return self.records.get(provenance_id)

    def find_by_value(self, value: Decimal) -> list[ProvenanceRecord]:
        """All verified records whose numeric_value matches — used by
        Checkpoint C to check "does ANY executed calculation support this
        claimed figure," since the LLM has no structured way to cite a
        specific calculation_id inline today."""
        return [
            r for r in self.records.values()
            if r.status == "verified" and r.normalized_value() == value
        ]

    def __bool__(self) -> bool:
        return bool(self.records)


def from_expression_record(record) -> ProvenanceRecord:
    """record: calculation.expression_evaluator.CalculationRecord"""
    return ProvenanceRecord(
        provenance_id=record.calculation_id,
        provenance_type="expression_derived",
        engine=record.engine,
        engine_version=record.engine_version,
        numeric_value=record.result,
        unit=record.unit,
        status=record.status,
        source_ref=record.expression,
    )


def from_formula_result(result) -> ProvenanceRecord:
    """result: calculation.formula_registry.FormulaResult"""
    return ProvenanceRecord(
        provenance_id=result.calculation_id,
        provenance_type="named_formula_result",
        engine=result.engine,
        engine_version=result.engine_version,
        numeric_value=result.output_value,
        unit=result.output_unit,
        status=result.status,
        source_ref=f"{result.formula_id}@{result.formula_version}",
    )


def from_policyengine_value(
    *, calculation_id: str, variable: str, value: float, engine_version: str = "policyengine_us",
) -> ProvenanceRecord:
    """PolicyEngine's existing integration (calculation/service.py) doesn't
    emit a CalculationRecord-shaped object today — it returns a
    CalculationResult with a raw {variable: float} dict, already surfaced
    to the model via a synthetic RAG chunk (to_calculation_rag_chunk), which
    the EXISTING retrieved_fact check already verifies correctly. This
    builder exists so a caller can *additionally* register a formal
    policy_engine_result provenance record for the same figure without
    requiring a redesign of the working PolicyEngine path — belt-and-braces,
    not a replacement."""
    return ProvenanceRecord(
        provenance_id=calculation_id,
        provenance_type="policy_engine_result",
        engine="policyengine_us",
        engine_version=engine_version,
        numeric_value=str(value),
        unit="USD",
        status="verified",
        source_ref=variable,
    )
