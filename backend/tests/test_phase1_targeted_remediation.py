"""Targeted control regressions. Synthetic fixtures are not live/accountant approval."""
import pytest
from app.orchestration.applicability import requires_rule_applicability, macroeconomic_only
from app.orchestration.answer_coverage import check_requested_deliverables
from app.orchestration.calculations.engine import calculate_from_query
from app.orchestration.retrieve import build_source_bundle
from tests.test_phase1_source_controls import store, proposal  # noqa: F401
from tests.offline_http_support import offline_http  # noqa: F401
from tests.test_agent_loop import _reply

QUESTION="Record the journal entry for a credit sale of £5,000 plus VAT at 20% by a UK VAT-registered business."
JOURNAL="""| Account | Debit | Credit |
|---|---:|---:|
| Trade receivables | £6,000 | - |
| Sales revenue | - | £5,000 |
| Output VAT payable | - | £1,000 |"""


@pytest.mark.parametrize("query", [
    "What should a tax return review checklist contain?", "What is tax?", "Explain input VAT.",
    "Net income is $1,000,000 with 500,000 shares; convertible interest is $60,000 and a 25% tax rate. Calculate diluted EPS.",
    "Compare inflation in India, the US and the UK for the last 3 years.",
])
def test_general_guidance_and_supplied_figures_are_not_local_law(query):
    assert not requires_rule_applicability(query)


@pytest.mark.parametrize("query", [
    "What VAT rate applies to hotel accommodation?", "What is the GST registration threshold?",
    "Can I reclaim input VAT legally?", "What is the filing deadline for my VAT return?",
    "What is the turnover limit for the VAT Cash Accounting Scheme?",
    "Explain who can use the VAT Cash Accounting Scheme.",
    "Compare inflation and current VAT rates in the UK and India.",
    "Compare statutory minimum wage rules and inflation in the UK and India.",
    "Using a 25% tax rate calculate EPS and check the current VAT registration threshold.",
    "Compare inflation adjustments required under IFRS in the UK and India.",
])
def test_rule_questions_keep_mandatory_applicability(query):
    assert requires_rule_applicability(query)
    assert not macroeconomic_only(query)


async def test_general_checklist_does_not_require_a_tax_jurisdiction(store):
    bundle=await build_source_bundle(store,query="What should a tax return review checklist contain?",jurisdiction="Any",tenant_id="t")
    assert not bundle.clarification_required and not bundle.passages


async def test_macro_comparison_keeps_all_country_labels_without_requiring_statutory_sources(store):
    bundle=await build_source_bundle(store,query="Compare inflation in India, the US and UK for the last 3 years.",jurisdiction="Any",tenant_id="t")
    assert not bundle.clarification_required
    assert set(bundle.jurisdiction.split(" / ")) == {"India","United States","United Kingdom"}
    assert not bundle.passages and bundle.eligible_source_count == 0
    assert bundle.confidence_state == "insufficient"


@pytest.mark.parametrize("query,jurisdiction", [
    ("What VAT rate applies?","Any"),
    ("What GST registration threshold applies?","Any"),
    ("What is the turnover limit for the VAT Cash Accounting Scheme?","Any"),
    ("UK VAT rate in 2024","United Kingdom"),
    ("Compare VAT rates in India and UK","Any"),
    ("Compare inflation in India and UK","United Kingdom"),
    ("UK VAT rate for FY 2024-25","United Kingdom"),
])
async def test_missing_rule_evidence_dates_and_conflicting_filters_still_clarify(store,query,jurisdiction):
    bundle=await build_source_bundle(store,query=query,jurisdiction=jurisdiction,tenant_id="t")
    assert bundle.clarification_required and not bundle.passages


async def test_macro_never_restores_a_pending_passage(store):
    await proposal(store,status="PROPOSED")
    bundle=await build_source_bundle(store,query="Compare inflation in India and UK",jurisdiction="Any",tenant_id="t")
    assert not bundle.passages


def journal_check(answer,question=QUESTION,calculation=True):
    checks=check_requested_deliverables(question,answer,calculation=calculate_from_query(question) if calculation else None)
    return next(c for c in checks if c.description == "Credit-sale journal entry")


@pytest.mark.parametrize("answer", [
    "VAT is £1,000 and the customer owes £6,000.",
    "Debit receivables, credit sales and output VAT.",
    JOURNAL.replace("£6,000","£5,000"),
    JOURNAL.replace("Sales revenue","Cash"),
    JOURNAL.replace("Output VAT payable", "Input VAT payable"),
    JOURNAL.replace("Trade receivables", "Bad debtors expense"),
    JOURNAL.replace("£5,000","£4,000").replace("£1,000","£2,000"),
    JOURNAL.replace("£","$"),
    JOURNAL.replace("Debit", "Debit (USD)").replace("£", ""),
    JOURNAL + "\n\n" + JOURNAL.replace("£5,000", "£4,000").replace("£1,000", "£2,000"),
    JOURNAL.replace("| Trade receivables | £6,000 | - |","| Trade receivables | - | £6,000 |"),
])
def test_missing_wrong_or_merely_balanced_journals_are_incomplete(answer):
    assert journal_check(answer).status == "incomplete"


@pytest.mark.parametrize("answer", [JOURNAL,"Dr Trade receivables £6,000; Cr Sales £5,000; Cr Output VAT £1,000."])
def test_explicit_journal_can_be_complete_only_when_validated_against_the_inputs(answer):
    assert journal_check(answer).status == "complete"
    assert journal_check(answer,calculation=False).status == "incomplete"


def test_no_unsolicited_credit_sale_journal_requirement():
    assert not any(c.description == "Credit-sale journal entry" for c in check_requested_deliverables(
        "Calculate VAT on £5,000 excluding VAT at 20%.","VAT £1,000, total £6,000."))


async def test_actual_credit_sale_http_failure_preserves_arithmetic_but_cannot_claim_complete(offline_http):
    result=await offline_http.ask(QUESTION,case_id="credit-sale-provider-unavailable")
    body=result.body
    assert body["answer"] is not None
    assert body["answer"]["completeness"] == "partial"
    assert body["answer"]["verification"]["overall"] != "fully_verified"
    assert any(c["description"] == "Credit-sale journal entry" and c["status"] == "incomplete" for c in body["requested_deliverables"])
    assert body["next_action"]["type"] == "journal_review_required"
    assert any(a["event"] == "answer_receipt" for a in result.trace["audit"])


async def test_actual_credit_sale_http_with_validated_journal_can_be_complete(offline_http):
    offline_http.state.responses=[_reply(JOURNAL)]
    result=await offline_http.ask(QUESTION,case_id="credit-sale-valid-journal")
    body=result.body
    assert body["answer"]["completeness"] == "complete", body["answer"]
    assert any(c["description"] == "Credit-sale journal entry" and c["status"] == "complete" for c in body["requested_deliverables"])


async def test_general_tax_checklist_reaches_composition_without_forced_jurisdiction(offline_http):
    offline_http.state.responses=[_reply("Review source documents, reconcile calculations and balances, document assumptions and exceptions, and arrange independent review. Specific local filing requirements require a jurisdiction.")]
    result=await offline_http.ask("What should a tax return review checklist contain?",case_id="general-checklist")
    assert result.body["outcome"] != "clarification_required"
    assert result.trace["model_requests"]


async def test_macro_http_uses_its_data_path_instead_of_statutory_clarification(offline_http):
    result=await offline_http.ask("Compare inflation in India, the US and the UK for the last 3 years, and show it as a chart.",case_id="macro-countries")
    assert not (result.body.get("source_bundle") or {}).get("clarification_required")
    assert result.body["outcome"] != "clarification_required"
    assert result.trace["model_requests"]


def test_unverified_canonical_calculation_cannot_certify_a_journal():
    calculation=calculate_from_query(QUESTION).model_copy(update={"verification_status":"not_run"})
    checks=check_requested_deliverables(QUESTION,JOURNAL,calculation=calculation)
    assert next(c for c in checks if c.description == "Credit-sale journal entry").status == "incomplete"
