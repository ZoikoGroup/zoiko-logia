"""Report states (ZL-RPT-007 §4). Only the first three are reachable from the
G1/G2 pipeline; the rest need professional review and issue controls."""
from __future__ import annotations

from enum import Enum


class ReportState(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    DRAFT_INCOMPLETE = "DRAFT_INCOMPLETE"
    DRAFT_RECONCILED = "DRAFT_RECONCILED"
    REVIEW_PENDING = "REVIEW_PENDING"
    REVIEWED = "REVIEWED"
    APPROVED_FOR_ISSUE = "APPROVED_FOR_ISSUE"
    ISSUED = "ISSUED"


# A reconciled draft is not audited, reviewed or approved for filing.
EXTERNALLY_ISSUABLE = frozenset({ReportState.ISSUED})
