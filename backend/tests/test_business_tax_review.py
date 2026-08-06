from app.domains.reference_data.business_tax_review import (
    BUSINESS_TAX_REVIEW_VERSION,
    compose_business_tax_review,
    to_business_tax_review_rag_chunk,
)
from app.domains.risk_safety.risk_classifier import classify
from app.orchestration.retrieve import infer_category


WORKFLOW_QUERY = (
    "Create a step-by-step workflow for reviewing a US business tax return before filing. "
    "Separate income-tax checks from payroll-tax checks."
)
INTAKE_QUERY = (
    "What information and jurisdiction details does Kriton need before answering "
    "a company-specific tax-treatment question?"
)


def test_business_tax_workflow_uses_closed_reviewed_category():
    assert infer_category(WORKFLOW_QUERY) == "business-tax-review"
    assert infer_category(INTAKE_QUERY) == "business-tax-review"


def test_business_tax_workflow_separates_income_and_employment_tax():
    answer = compose_business_tax_review(WORKFLOW_QUERY, "REF-1")
    assert "### A. Scope and income-tax return" in answer
    assert "### B. Separate employment-tax review" in answer
    assert "Form 1120, 1120-S or 1065" in answer
    assert "Forms 940, 941, 943, 944 or 945" in answer
    assert "these are not the entity's general income-tax return" in answer
    assert "obsolete general \"allowances claimed\" checklist" in answer
    assert answer.count("[REF-1]") >= 10


def test_company_specific_tax_intake_does_not_require_company_name_or_sec_filing():
    answer = compose_business_tax_review(INTAKE_QUERY, "REF-1")
    assert "Company name is needed only" in answer
    assert "Entity and tax classification" in answer
    assert "transaction steps, contracts, amounts" in answer.lower()
    assert "SEC Form" not in answer


def test_reviewed_tax_chunk_is_dated_and_links_to_irs():
    chunk = to_business_tax_review_rag_chunk(WORKFLOW_QUERY)
    assert chunk["metadata"]["version"] == BUSINESS_TAX_REVIEW_VERSION
    assert chunk["metadata"]["file_path"] == "https://www.irs.gov/filing"
    assert "reviewed 2026-07-29" in chunk["text"]


def test_reviewed_tax_questions_use_high_risk_cited_route():
    for query in (WORKFLOW_QUERY, INTAKE_QUERY):
        decision = classify(query, jurisdiction="US", source_confidence="HIGH_CONFIDENCE")
        assert decision["allowed"] is True
        assert decision["risk_level"] == "HIGH"
        assert decision["route"] == "LLM"
        assert decision["requires_citation"] is True
        assert decision["requires_professional_boundary"] is True
        assert "l2-deterministic-reviewed-tax-workflow" in decision["rules_applied"]
