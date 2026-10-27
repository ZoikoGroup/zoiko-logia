"""Run the Document 04 intake on an uploaded trial balance: receive, parse,
normalise, check and propose mappings. Stateless: the result is returned,
not stored (persistence needs a database migration, a later step)."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import integrity, intake, mapping, normalize, workflow
from .findings import Finding


@dataclass
class IntakeResult:
    manifest: intake.SourceManifest
    tb: normalize.NormalizedTB
    report: integrity.IntegrityReport
    mappings: list[mapping.MappingProposal] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    state: str = workflow.RECEIVED

    def to_dict(self) -> dict:
        counts = {s: sum(1 for m in self.mappings if m.status == s)
                  for s in (mapping.SUGGESTED, mapping.NEEDS_EVIDENCE, mapping.UNMAPPED, mapping.APPROVED)}
        return {
            "state": self.state,
            "manifest": self.manifest.to_dict(),
            "units": self.tb.units,
            "sign_convention": self.tb.sign_convention,
            "integrity": self.report.to_dict(),
            "findings": [f.to_dict() for f in self.findings],
            "lines": [l.to_dict() for l in self.tb.lines],
            "mappings": [m.to_dict() for m in self.mappings],
            "mapping_counts": counts,
            "status_note": "Proposals only: every mapping needs a reviewer's approval, and nothing is posted.",
        }


def run_intake(filename: str, content: bytes, uploaded_by: str) -> IntakeResult:
    parsed = intake.receive(filename, content, uploaded_by)
    if parsed.rejected:
        return IntakeResult(manifest=parsed.manifest, tb=normalize.NormalizedTB(),
                            report=integrity.IntegrityReport(), findings=list(parsed.findings),
                            state=workflow.REJECTED_SOURCE)
    tb = normalize.normalize(parsed)
    report = integrity.check(tb)
    findings = [*parsed.findings, *tb.findings, *report.findings]
    mappings = mapping.propose_all(tb)
    return IntakeResult(manifest=parsed.manifest, tb=tb, report=report, mappings=mappings, findings=findings,
                        state=workflow.state_of(findings, mappings, []))
