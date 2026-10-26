"""Findings raised by the trial-balance pipeline (Document 04 §10, §12).

HARD_STOP blocks approval of the snapshot; REVIEW needs a reviewer's
disposition; INFO records something the reader should know.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

HARD_STOP, REVIEW, INFO = "HARD_STOP", "REVIEW", "INFO"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    rule: str                      # Document 04 rule, e.g. "SD-013"
    refs: tuple[str, ...] = field(default_factory=tuple)   # sheet!row or account keys

    def to_dict(self) -> dict:
        return {**asdict(self), "refs": list(self.refs)}


def blocking(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == HARD_STOP]
