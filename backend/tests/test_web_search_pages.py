"""Web search quality fixes (2026-09-28): one search per question, official
pages read with tables labelled by column, the relevant part excerpted."""
from app.orchestration.websearch import (
    _html_to_text, _readable_host, _relevant_excerpt, sub_questions,
)

MULTI = ("What are the income tax slabs under India's new regime for FY 2025-26? "
         "What is the standard deduction for salaried employees in India this year? "
         "What is the VAT registration threshold in the UK?")


def test_each_question_is_searched_separately() -> None:
    assert sub_questions(MULTI) == [
        "What are the income tax slabs under India's new regime for FY 2025-26?",
        "What is the standard deduction for salaried employees in India this year?",
        "What is the VAT registration threshold in the UK?",
    ]


def test_single_question_is_one_search() -> None:
    assert sub_questions("What is deferred tax?") == ["What is deferred tax?"]


SLAB_TABLE = """
<p>Menu</p><p>Tax slabs</p><p>Tax slabs</p>
<table>
 <tr><th colspan="2">Old Tax Regime</th><th colspan="2">New Tax Regime</th></tr>
 <tr><th>Income Tax Slab</th><th>Rate</th><th>Income Tax Slab</th><th>Rate</th></tr>
 <tr><td><div>Up to &#8377; 2,50,000</div></td><td>Nil</td><td>Up to &#8377; 4,00,000</td><td>Nil</td></tr>
 <tr><td>&#8377; 2,50,001 &ndash; &#8377; 5,00,000</td><td>5%</td><td>&#8377; 4,00,001 &ndash; &#8377; 8,00,000</td><td>5%</td></tr>
</table>
<p>Surcharge applies to income above 50 lakh income income income.</p>
"""


def test_table_cells_are_labelled_with_their_column_heading() -> None:
    text = _html_to_text(SLAB_TABLE)
    row = next(line for line in text.splitlines() if "4,00,000" in line)
    assert "New Tax Regime – Income Tax Slab: Up to ₹ 4,00,000" in row
    assert "Old Tax Regime – Income Tax Slab: Up to ₹ 2,50,000" in row


def test_excerpt_prefers_the_figure_table_over_repeated_prose() -> None:
    excerpt = _relevant_excerpt(_html_to_text(SLAB_TABLE), "What are the income tax slabs under the new regime?")
    assert "Up to ₹ 4,00,000" in excerpt
    assert excerpt.count("Tax slabs") <= 1  # duplicate menu lines dropped


def test_only_official_or_allowlisted_hosts_are_read() -> None:
    assert _readable_host("https://www.incometax.gov.in/iec/page", [])
    assert _readable_host("https://www.gov.uk/how-vat-works/vat-thresholds", [])
    assert _readable_host("https://www.ifrs.org/issued-standards/", [])
    assert not _readable_host("https://random-blog.example.com/tax", [])
    assert not _readable_host("ftp://www.gov.uk/file", [])
