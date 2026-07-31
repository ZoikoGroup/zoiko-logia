from app.domains.coverage import assess_us_professional_coverage
from app.orchestration.schemas import SourceBundle, SourceSummary


def _bundle(*titles: str) -> SourceBundle:
    sources = [
        SourceSummary(
            id=f"src-{index}", title=title, category="standards",
            jurisdiction_scope="US", version_label="current", status="ACTIVE",
        )
        for index, title in enumerate(titles)
    ]
    return SourceBundle(
        source_bundle_id="bundle-test", eligible_source_count=len(sources),
        sources=sources, jurisdiction="US", licence_state="permitted",
        confidence_state="sufficient",
    )


def test_revenue_question_is_covered_by_asc_606():
    decision = assess_us_professional_coverage(
        "How is revenue recognition handled under US GAAP?",
        _bundle("ASC 606 — Revenue from Contracts with Customers (FASB)"),
    )
    assert decision.applies is True
    assert decision.covered is True
    assert decision.topic == "revenue"


def test_lease_question_is_not_covered_by_unrelated_asc_606():
    decision = assess_us_professional_coverage(
        "Explain lease accounting under ASC 842.",
        _bundle("ASC 606 — Revenue from Contracts with Customers (FASB)"),
    )
    assert decision.applies is True
    assert decision.covered is False
    assert decision.required_authority == "FASB ASC 842"


def test_internal_control_audit_is_covered_by_as_2201():
    decision = assess_us_professional_coverage(
        "What does an ICFR audit require?",
        _bundle("PCAOB AS 2201 — An Audit of Internal Control Over Financial Reporting"),
    )
    assert decision.covered is True


def test_single_audit_requires_its_own_authority():
    decision = assess_us_professional_coverage(
        "What procedures are required in a Single Audit?",
        _bundle("US Generally Accepted Auditing Standards (GAAS)"),
    )
    assert decision.applies is True
    assert decision.covered is False


def test_broad_partnership_tax_is_blocked_without_matching_guidance():
    decision = assess_us_professional_coverage(
        "Explain partnership tax and Form 1065.",
        _bundle("IRS Publication 946 — How to Depreciate Property"),
    )
    assert decision.applies is True
    assert decision.covered is False


def test_unregistered_topic_does_not_claim_coverage_or_block_existing_flow():
    decision = assess_us_professional_coverage(
        "What is the accrual basis of accounting?", _bundle("General accounting guide")
    )
    assert decision.applies is False
    assert decision.covered is True


def test_standard_deduction_amount_requires_tax_year():
    decision = assess_us_professional_coverage(
        "What is the standard deduction for a single filer?",
        _bundle("IRS Direct File Fact Dictionary — Standard Deduction"),
    )
    assert decision.covered is False
    assert decision.action == "clarification_required"
    assert "tax year" in decision.message.lower()


def test_standard_deduction_with_year_can_continue():
    decision = assess_us_professional_coverage(
        "What is the standard deduction for a single filer in 2025?",
        _bundle("IRS Direct File Fact Dictionary — Standard Deduction"),
    )
    assert decision.applies is False


def test_conceptual_standard_vs_itemized_flowchart_does_not_require_year():
    decision = assess_us_professional_coverage(
        "Show a decision flowchart for determining whether a taxpayer should use the standard deduction or consider itemizing deductions.",
        _bundle("IRS Direct File Fact Dictionary — Standard Deduction"),
    )

    assert decision.applies is False
    assert decision.covered is True


def test_bill_status_requires_congress_source_not_policyengine():
    decision = assess_us_professional_coverage(
        "What is the status of H.R. 1 in the 119th Congress?",
        _bundle("PolicyEngine-US Parameters — Federal Tax Credits"),
    )
    assert decision.applies is True
    assert decision.covered is False
    assert decision.required_authority == "Congress.gov bill record"


def test_bill_status_is_covered_by_congress_record():
    decision = assess_us_professional_coverage(
        "What is the status of H.R. 1 in the 119th Congress?",
        _bundle("Congress.gov — Bill Lookup"),
    )
    assert decision.covered is True


def test_unavailable_treasury_gbp_rate_requests_supported_source():
    decision = assess_us_professional_coverage(
        "What is the latest US Treasury exchange rate for the British pound?",
        _bundle("US Treasury Fiscal Data — Rates of Exchange"),
    )
    assert decision.covered is False
    assert decision.action == "clarification_required"
    assert "GBP" in decision.message
