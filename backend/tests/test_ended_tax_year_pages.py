"""Web pages titled for a tax year that has ended are left out of the evidence
for a question that names no year (3 Nov 2026): "Rates and thresholds for
employers 2024 to 2025" (13.8%) made the claim judge reject the correct
current 15% for UK employer National Insurance."""
from datetime import date

import pytest

from app.orchestration.websearch import WebSource, ended_tax_year, without_ended_tax_years

TODAY = date(2026, 11, 3)
OLD = WebSource(title="Rates and thresholds for employers 2024 to 2025 - GOV.UK",
                url="https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2024-to-2025", snippet="13.8%")
CURRENT = WebSource(title="Rates and thresholds for employers 2026 to 2027",
                    url="https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027", snippet="15%")
BULLETIN = WebSource(title="Autumn Budget 2024 - GAD Technical Bulletin", url="https://www.gov.uk/gad", snippet="13.8% to 15%")


@pytest.mark.parametrize("title, ended", [
    ("Rates and thresholds for employers 2024 to 2025 - GOV.UK", True),
    ("Income tax rates 2023/24", True),
    ("Budget 2024-25 highlights", True),
    ("Rates and thresholds for employers 2025 to 2026", False),   # may still apply somewhere
    ("Rates and thresholds for employers 2026 to 2027", False),
    ("Autumn Budget 2024 - GAD Technical Bulletin", False),       # a year, not a tax year
    ("IFRS annual improvements 2016-2018 cycle", False),
])
def test_ended_tax_year(title, ended):
    assert ended_tax_year(title, today=TODAY) is ended


def test_a_current_question_drops_the_ended_tax_year_page():
    kept = without_ended_tax_years([OLD, CURRENT, BULLETIN],
                                   "What is the current UK employer National Insurance contribution rate?", today=TODAY)
    assert kept == [CURRENT, BULLETIN]


def test_a_question_about_that_year_keeps_it():
    sources = [OLD, CURRENT]
    assert without_ended_tax_years(sources, "What was the employer NI rate in 2024?", today=TODAY) == sources
    assert without_ended_tax_years(sources, "Employer NI rate for 2024/25?", today=TODAY) == sources


def test_nothing_is_removed_when_it_is_all_there_is():
    assert without_ended_tax_years([OLD], "What is the employer NI rate?", today=TODAY) == [OLD]


def test_a_fixed_official_page_is_never_removed():
    assert without_ended_tax_years([OLD, CURRENT], "What is the employer NI rate?", protected={OLD.url}, today=TODAY) == [OLD, CURRENT]
