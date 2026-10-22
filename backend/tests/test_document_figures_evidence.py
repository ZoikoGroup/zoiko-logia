"""Figures computed from an attached file are evidence for that file.

"Dr Depreciation 137,085" is cost ÷ useful life, not a line in the register.
Claim verification read only the raw rows, judged it unsupported and pruned
the answer to "the sources do not state…" (shown as Partially answered).
"""
from types import SimpleNamespace

from app.orchestration.service import _document_figures_evidence

BLOCK = "\n\n=== Verified figures computed by Kriton from the attached documents ===\n- Annual straight-line depreciation: total = 137,085"


def _source(source_id, provider="uploaded_document"):
    return SimpleNamespace(source_id=source_id, title=f"{source_id} — Register", provider=provider)


def test_the_block_is_evidence_once_per_file_under_its_reference():
    citations = [SimpleNamespace(ref_id="REF-1"), SimpleNamespace(ref_id="REF-2"), SimpleNamespace(ref_id="REF-3")]
    sources = [_source("doc-assets"), _source("doc-assets"), _source("https://www.ifrs.org", provider=None)]
    evidence = _document_figures_evidence(BLOCK, citations, sources)
    assert evidence == [f"[REF-1] {BLOCK.strip()}"]
    assert "137,085" in evidence[0]


def test_nothing_is_added_without_figures_or_without_a_file():
    citations = [SimpleNamespace(ref_id="REF-1")]
    assert _document_figures_evidence("", citations, [_source("doc-assets")]) == []
    assert _document_figures_evidence(BLOCK, citations, [_source("https://www.gov.uk", provider=None)]) == []
