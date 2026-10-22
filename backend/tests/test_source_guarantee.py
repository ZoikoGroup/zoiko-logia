"""Every answer names where it comes from (source_guarantee.py)."""
from types import SimpleNamespace

from app.orchestration.source_guarantee import keep_document_citations, official_sources_note


def _c(ref, source_id, provider="uploaded_document"):
    return SimpleNamespace(ref_id=ref, source_id=source_id, provider=provider)


def test_an_answer_from_a_file_lists_the_file_even_without_a_marker():
    available = [_c("REF-1", "doc-assets"), _c("REF-2", "doc-assets"), _c("REF-3", "doc-tb"),
                 _c("REF-4", "https://www.ifrs.org", provider=None)]
    kept = keep_document_citations([], available)
    assert [c.ref_id for c in kept] == ["REF-1", "REF-3"]          # one per file; web hits not added


def test_cited_references_are_kept_and_files_not_repeated():
    available = [_c("REF-1", "doc-assets"), _c("REF-2", "doc-assets"), _c("REF-3", "https://www.ifrs.org", provider=None)]
    cited = [available[1], available[2]]
    assert [c.ref_id for c in keep_document_citations(cited, available)] == ["REF-2", "REF-3"]


def test_the_official_sources_match_the_topic_and_are_labelled_as_suggestions():
    note = official_sources_note("How is input tax credit claimed under GST?")
    assert "suggestions, not evidence" in note and "cbic-gst.gov.in" in note
    assert "ifrs.org" in official_sources_note("Explain IAS 16 depreciation methods")
    assert "gov.uk/hmrc" in official_sources_note("When is VAT registration required?")
    assert "ifrs.org" in official_sources_note("What is working capital?")          # default
    assert official_sources_note("IFRS 16 vs US GAAP ASC 842 audit").count(";") <= 2  # at most three
