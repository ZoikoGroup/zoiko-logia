"""Figures extracted from an attached document with their page are cited to
that page's passage (qry-2be1a1670944 went to review: 'lacks a valid citation')."""
from types import SimpleNamespace as C

from app.orchestration.document_citations import cite_document_pages
from app.orchestration.verification_service import release_claims

PAGES = [C(ref_id="REF-1", title="balance_sheet.pdf — Page 1"), C(ref_id="REF-2", title="balance_sheet.pdf — Page 2")]


def test_a_table_row_naming_its_page_gets_that_pages_citation():
    cited = cite_document_pages("| Cash and cash equivalents | 45,000 | Page 1 – Current Assets | High |", PAGES)
    assert cited.endswith("[REF-1] |")
    # The release check now reads the row as cited to page 1's passage.
    assert any("[REF-1]" in claim for claim in release_claims(cited))


def test_sentences_already_cited_or_without_a_page_are_unchanged():
    text = "Total assets are 105,500 [REF-2] on page 1.\nThe figures balance."
    assert cite_document_pages(text, PAGES) == text


def test_a_page_the_document_does_not_have_is_not_invented():
    assert "[REF" not in cite_document_pages("| Borrowings | 25,000 | Page 7 |", PAGES)


def test_web_sources_without_pages_change_nothing():
    web = [C(ref_id="REF-1", title="IFRS 18 — IFRS Foundation")]
    assert cite_document_pages("Revenue on page 1.", web) == "Revenue on page 1."
