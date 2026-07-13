"""
Massarius™ retrieval and evidence subsystem — typed control-failure exceptions
(ZL-ENG-03 §5.3, §6).

Every exception here carries enough structured context to populate its audit
event without the caller needing to re-derive anything. All are subclasses of
MassariusError so orchestration/service.py can catch the whole family at one
call site and map it to an audit event + a terminal/degraded route — never an
unhandled 500.

This module must NOT contain control logic itself (that's license_gate.py,
bundle_builder.py, answer_validator.py) — only the exception taxonomy.
"""
from __future__ import annotations

from typing import Literal, Optional


class MassariusError(Exception):
    """Base class for every Massarius™ control-failure exception."""


class RetrievalFailed(MassariusError):
    """Retrieval itself could not complete (distinct from finding zero eligible
    sources, which is a normal confidence_state outcome, not a failure)."""

    def __init__(self, reason: str, *, query_id: Optional[str] = None):
        self.reason = reason
        self.query_id = query_id
        super().__init__(reason)


class LicenceDenied(MassariusError):
    """A source failed Checkpoint A or Checkpoint B eligibility. Carries the
    checkpoint identifier, the offending source(s), and a reason code so the
    licence_denied audit event never needs to re-derive this after the fact."""

    def __init__(
        self,
        checkpoint: Literal["A", "B", "C"],
        source_ids: list[str],
        reason_code: str,
    ):
        self.checkpoint = checkpoint
        self.source_ids = source_ids
        self.reason_code = reason_code
        super().__init__(f"Checkpoint {checkpoint} denied {source_ids}: {reason_code}")


ContextOverflowKind = Literal[
    "low_priority_overflow",            # non-mandatory sources dropped to fit budget — safe
    "mandatory_source_overflow",        # a mandatory source itself doesn't fit — unsafe to proceed
    "citation_preservation_impossible",  # fitting would break citation integrity — unsafe to proceed
]


class ContextOverflow(MassariusError):
    """Raised by a future context_fit.py (Phase 3) when assembled context
    exceeds the model's context budget. The taxonomy is defined now, in
    Phase 1, because bundle_builder.py's confidence_state reasoning already
    needs to distinguish "some low-priority sources got dropped" (safe) from
    "a mandatory source or citation integrity itself couldn't survive
    trimming" (must degrade the route, not just quietly proceed)."""

    def __init__(self, kind: ContextOverflowKind, detail: str = ""):
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind}: {detail}" if detail else kind)


class CitationBindingFailed(MassariusError):
    """A citation marker in a composed answer doesn't resolve to a passage
    in the CitationMap — raised by answer_validator.py's citation check."""

    def __init__(self, unbound_citation_ids: list[str]):
        self.unbound_citation_ids = unbound_citation_ids
        super().__init__(f"Unbound citations: {unbound_citation_ids}")


class ValidationFailed(MassariusError):
    """Checkpoint C failed one or more answer_validator.py checks. Carries
    the same failures/degraded_route shape as ValidationResult so a caller
    that wants to catch-and-convert (see answer_validator.py's public
    function) doesn't have to reconstruct anything."""

    def __init__(self, failures: list[str], degraded_route: str = "REFUSAL"):
        self.failures = failures
        self.degraded_route = degraded_route
        super().__init__("; ".join(failures) or "validation failed")
