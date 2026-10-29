import pytest

from app.orchestration.websearch import WebSource, _is_relevant
from app.orchestration.websearch import _publication_pdf


@pytest.mark.parametrize("query,title,snippet", [
    ("permanent establishment audit focus and preparation steps", "Evaluation and internal audit", "OECD's internal audit and evaluation responsibilities."),
    ("permanent establishment audit focus", "Improving control and audit in public integrity", "An institutional review of anti-corruption controls."),
    ("withholding tax compliance and audit focus", "Compliance management: Tax Administration", "Tax administration performance ratios and compliance management."),
    ("lease accounting documentation requirements", "Documentation requirements", "Documentation and preparation guidance for a compliance audit."),
])
def test_generic_task_word_matches_do_not_make_a_source_about_the_technical_subject(query, title, snippet):
    assert not _is_relevant(query, WebSource(title=title, url="https://oecd.org/example", snippet=snippet))


@pytest.mark.parametrize("query,title,snippet", [
    ("permanent establishment audit focus", "Attribution of income to permanent establishments", "Income attributable under an income tax treaty."),
    ("transfer pricing audit preparation", "Transfer pricing documentation guidance", "Documentation for associated enterprises."),
    ("What is IPR?", "Intellectual Property Rights", "The principles of intellectual property rights."),
    ("audit documentation requirements", "Audit documentation", "Documentation supporting an auditor's work."),
])
def test_subject_matches_abbreviations_and_genuinely_general_queries_remain_usable(query, title, snippet):
    assert _is_relevant(query, WebSource(title=title, url="https://oecd.org/example", snippet=snippet))


def test_source_framework_is_filtered_before_it_consumes_a_result_slot():
    foreign = WebSource(title="IAS 37 provisions", url="https://ifrs.org/example", snippet="Income tax uncertainty recognition and measurement under IFRS.")
    query = "ASC 740 income tax uncertainty recognition and measurement"
    assert not _is_relevant(query, foreign)
    assert _is_relevant("Compare ASC 740 and IAS 37 income tax uncertainty recognition", foreign)


def test_only_explicit_publication_downloads_on_the_same_publisher_are_followed():
    url = "https://www.oecd.org/en/publications/report.html"
    assert _publication_pdf('<a href="/content/report.pdf">Download PDF</a>', url) == 'https://www.oecd.org/content/report.pdf'
    assert _publication_pdf('<a href="https://other.example/report.pdf">Download PDF</a>', url) is None
    assert _publication_pdf('<a href="/privacy.pdf">Privacy notice</a>', url) is None
    assert _publication_pdf('<meta name="citation_pdf_url" content="/content/report.pdf">', url).endswith('/content/report.pdf')


def test_concept_passages_are_not_displaced_by_unrelated_numeric_tables():
    from app.orchestration.websearch import _relevant_excerpt
    prose = "\n".join(["Obligation recognition depends on the underlying contractual terms."] * 3)
    tables = "\n".join(f"Financial example {index}: 10%, 20%, $100,000" for index in range(80))
    result = _relevant_excerpt(prose + "\n" + tables, "obligation recognition contractual terms", limit=300)
    assert "underlying contractual terms" in result


def test_known_download_resolution_is_by_publication_identity_not_question_text():
    from app.orchestration.publication_catalogue import PUBLICATION_DOWNLOADS, known_publication_download
    page, document = next(iter(PUBLICATION_DOWNLOADS.items()))
    assert known_publication_download(page + '?download=true') == document
    assert known_publication_download('https://different.example/' + page.rsplit('/',1)[-1]) is None


def test_hosted_public_comments_are_not_current_governing_guidance():
    source = WebSource(title="Comments from Academia on the Revised Discussion Draft on Transfer Pricing Aspects of Intangibles",
                       url="https://oecd.org/public-comments.pdf", snippet="Transfer pricing intangible ownership returns.")
    assert not _is_relevant("Transfer pricing intangible ownership returns", source)
    assert _is_relevant("Discussion draft comments on transfer pricing intangibles", source)
