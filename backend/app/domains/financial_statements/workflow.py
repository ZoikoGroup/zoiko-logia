"""Intake states and the approved ledger snapshot (Document 04 stages P6–P8,
§12 state machine, rules SD-010, SD-040).

RECEIVED → PARSED → RECONCILIATION_FAILED | MAPPING_REVIEW → ADJUSTMENT_PENDING
→ VALIDATED_DRAFT → APPROVED_SNAPSHOT; SUPERSEDED when the source changes.

The snapshot is approved only by someone other than the preparer, only with
no hard stop, every account mapped and approved, and every journal reviewed.
Its content hash covers the source fingerprint, every line, every mapping
decision and every approved journal: any change makes a new hash and the old
approval no longer matches (SD-010).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from .findings import Finding, blocking
from .journals import JournalProposal, line_totals
from .mapping import APPROVED, MappingProposal
from .normalize import NormalizedTB

REJECTED_SOURCE = "REJECTED"
RECEIVED, PARSED, RECONCILIATION_FAILED = "RECEIVED", "PARSED", "RECONCILIATION_FAILED"
MAPPING_REVIEW, ADJUSTMENT_PENDING, VALIDATED_DRAFT = "MAPPING_REVIEW", "ADJUSTMENT_PENDING", "VALIDATED_DRAFT"
APPROVED_SNAPSHOT, SUPERSEDED = "APPROVED_SNAPSHOT", "SUPERSEDED"


class ApprovalError(ValueError):
    pass


def state_of(findings: list[Finding], mappings: list[MappingProposal], journals: list[JournalProposal],
             rejected: bool = False) -> str:
    if rejected:
        return REJECTED_SOURCE
    if blocking(findings):
        return RECONCILIATION_FAILED
    if any(m.status != APPROVED for m in mappings):
        return MAPPING_REVIEW
    if any(j.review_status == "PENDING_REVIEW" for j in journals):
        return ADJUSTMENT_PENDING
    return VALIDATED_DRAFT


def content_hash(source_sha256: str, tb: NormalizedTB | list[dict], mappings: list[MappingProposal],
                 journals: list[JournalProposal]) -> str:
    """tb is the normalised trial balance, or its stored line dicts."""
    payload = {
        "source": source_sha256,
        "lines": tb if isinstance(tb, list) else [l.to_dict() for l in tb.lines],
        "mappings": [m.to_dict() for m in mappings],
        "journals": [j.to_dict() for j in journals if j.review_status == "APPROVED"],
    }
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ApprovedLedgerSnapshot:
    snapshot_id: str
    content_hash: str
    source_sha256: str
    preparer: str
    approver: str
    approved_at: str
    line_totals: dict

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def approve_snapshot(*, source_sha256: str, tb: NormalizedTB | list[dict], findings: list[Finding],
                     mappings: list[MappingProposal], journals: list[JournalProposal],
                     preparer: str, approver: str) -> ApprovedLedgerSnapshot:
    if approver == preparer:
        raise ApprovalError("The preparer cannot approve their own trial balance (segregation of duties).")
    state = state_of(findings, mappings, journals)
    if state != VALIDATED_DRAFT:
        reasons = {RECONCILIATION_FAILED: "hard stops are open: " + "; ".join(f.code for f in blocking(findings)),
                   MAPPING_REVIEW: "some accounts are not mapped and approved",
                   ADJUSTMENT_PENDING: "some journals are still pending review"}
        raise ApprovalError(f"Cannot approve: {reasons.get(state, state)}.")
    digest = content_hash(source_sha256, tb, mappings, journals)
    totals = {k: str(v) for k, v in line_totals(mappings).items()}
    return ApprovedLedgerSnapshot(snapshot_id="snap-" + digest[7:23], content_hash=digest,
                                  source_sha256=source_sha256, preparer=preparer, approver=approver,
                                  approved_at=datetime.now(timezone.utc).isoformat(), line_totals=totals)


def still_valid(snapshot: ApprovedLedgerSnapshot, *, source_sha256: str, tb: NormalizedTB | list[dict],
                mappings: list[MappingProposal], journals: list[JournalProposal]) -> bool:
    """False once the source, a line, a mapping or a journal changes (SD-010)."""
    return snapshot.content_hash == content_hash(source_sha256, tb, mappings, journals)
