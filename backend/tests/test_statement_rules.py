"""Document 01 rules on financial-statement answers (statement_rules.py)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.model_gateway.agent import AgentOutcome
from app.orchestration import learned_answers, review, service
from app.orchestration.schemas import AskKritonRequest
from app.orchestration.statement_rules import (
    CASH_FLOW_NOTE, COMPARATIVES_NOTE, STATUS_NOTE, is_statement_request, open_items, remove_unsupported_claims,
)


def test_statement_requests_are_recognised():
    for question in ("Generate income statement", "Prepare the financial statements from this trial balance",
                     "Show the balance sheet", "Prepare a cash flow statement", "P&L for the year",
                     "Statement of changes in equity"):
        assert is_statement_request(question), question
    for question in ("What is income tax?", "Prepare the VAT summary", "Show total sales by month",
                     # Checking or comparing statements is not preparing them (QA B03, G01).
                     "Confirm that the balance sheet, cash-flow ending cash, and equity roll-forward all reconcile.",
                     "Sum quarterly revenue and compare with the financial statement.",
                     "What is a balance sheet?", "Explain the cash flow statement"):
        assert not is_statement_request(question), question


def test_statement_rules_ask_for_each_account_under_its_heading():
    # One run listed each expense, another showed only "Operating expenses 574,000".
    from app.orchestration.statement_rules import INSTRUCTIONS

    assert "List every account on its own line under its heading" in INSTRUCTIONS
    assert "no leading dash" in INSTRUCTIONS


def test_fiscal_year_labels_in_a_statement_pdf_count_as_comparatives():
    # "Prior-year figures: not provided" was said of a PDF stating FY2024 revenue.
    pdf = "Figures stated in 'NB.pdf' (released), Page 1: FY2025 Revenue 10,000; FY2024 Revenue 8,000"
    assert COMPARATIVES_NOTE not in open_items("Generate income statement", "", pdf)
    assert COMPARATIVES_NOTE in open_items("Generate income statement", "", "FY2025 Revenue 10,000")


def test_unsupported_claims_are_removed_and_honest_ones_kept():
    text = ("Profit for the year is 590,250.\n"
            "These statements are fully compliant with FRS 102. They have been audited.\n"
            "The accounts are not audited and must be reviewed by an accountant.\n"
            "The tax of 196,750 remains unpaid.\n"
            "We cannot tell whether the tax is unpaid without the payment records.\n"
            "| Line | Amount |\n| Audited total | 1 |")
    kept, removed = remove_unsupported_claims(text)
    assert "fully compliant" not in kept and "have been audited" not in kept and "remains unpaid" not in kept
    assert "not audited and must be reviewed" in kept and "cannot tell whether the tax is unpaid" in kept
    assert "| Audited total | 1 |" in kept          # tables are left alone
    assert "Profit for the year is 590,250." in kept and len(removed) == 3


def test_open_items_name_the_draft_status_missing_comparatives_and_name_based_classifications():
    tb = "account_code\taccount_name\tdebit\tcredit\n6000\tUtilities\t18400\t\n6100\tBank charges\t2900\t"
    notes = open_items("Generate income statement", "Utilities 18,400", tb)
    assert notes[0] == STATUS_NOTE and COMPARATIVES_NOTE in notes
    assert any("Utilities" in n and "Bank charges" in n for n in notes)
    two_years = "account_name\t2026\t2025\nRevenue\t100\t90"
    assert COMPARATIVES_NOTE not in open_items("Generate income statement", "", two_years)
    assert CASH_FLOW_NOTE in open_items("Prepare a cash flow statement", "", tb)


ANSWER = ("**Income statement**\n\n| Line | 2026 |\n| Revenue | 4,182,000 |\n| Profit for the year | 590,250 |\n\n"
          "These financial statements are compliant with FRS 102.")
FIGURES = ("\n\n=== Verified figures computed by Kriton from the attached documents ===\n"
           "Trial balance 'tb.csv': total debits = 7,026,500; total credits = 7,026,500; difference = 0\n"
           "- Income statement: Revenue = 4,182,000; Profit for the year = 590,250")


@pytest.fixture
def pipeline(monkeypatch):
    for name in dir(service):
        if name.startswith("audit_"):
            monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, "_finalise_and_return", AsyncMock())
    monkeypatch.setattr(service, "list_authorized_engagements", AsyncMock(return_value=[]))
    monkeypatch.setattr(review, "record_answer", AsyncMock())
    monkeypatch.setattr(learned_answers, "feedback_guidance", AsyncMock(return_value=""))
    monkeypatch.setattr(service, "build_source_bundle", AsyncMock(side_effect=RuntimeError("no governed library in tests")))
    monkeypatch.setattr(service, "web_search_each", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "classify_risk", AsyncMock(return_value="LOW"))
    monkeypatch.setattr(service, "classify_risk_gemini", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "select_prompt", AsyncMock(return_value=SimpleNamespace(
        id="prompt-test", mode="agent", template="{query}", version="1", model_hint=None)))
    monkeypatch.setattr(service, "_verified_document_figures_context", AsyncMock(return_value=FIGURES))
    monkeypatch.setattr(service.model_gateway_service, "agent_mode_active", lambda: True)
    agent = AsyncMock(return_value=AgentOutcome(text=ANSWER))
    monkeypatch.setattr(service.model_gateway_service, "run_agentic_completion", agent)
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=""))
    return agent


async def test_an_income_statement_answer_is_labelled_a_draft_without_a_compliance_claim(pipeline):
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query="Generate income statement"))
    assert "590,250" in response.answer.text and "compliant with FRS 102" not in response.answer.text
    assert response.answer.limitations[0] == STATUS_NOTE and COMPARATIVES_NOTE in response.answer.limitations
    prompt = str(pipeline.await_args)
    assert "Financial statement rules (ZoikoLogia Document 01)" in prompt


async def test_other_questions_are_unchanged(pipeline):
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query="Summarise the revenue in this file"))
    assert STATUS_NOTE not in response.answer.limitations
    assert "Financial statement rules" not in str(pipeline.await_args)


# ── Document 01 §17.1 benchmark tests and the remaining chat rules ───────────
from app.orchestration.document_figures import verified_document_figures  # noqa: E402
from app.orchestration.statement_rules import (  # noqa: E402
    FRAMEWORK_UNKNOWN_NOTE, RATIOS_NOTE, RULES, UNRECONCILED_NOTE, output_class,
)
from app.orchestration.websearch import WebSource  # noqa: E402


def _figures(rows):
    return verified_document_figures([WebSource(title="tb.csv — Sheet1", url="", snippet="\n".join(rows), source_id="d1")])


NORTHBRIDGE = ["account_name\tdebit\tcredit", "Revenue\t\t1850000", "Cost of sales\t1054500\t",
               "Utilities\t18400\t", "Marketing\t42600\t", "Bank charges\t2900\t", "Interest income\t\t12000",
               "Interest payable\t14200\t", "Corporation tax charge\t62000\t", "Cash at bank\t1000000\t",
               "Share capital\t\t1083500", "Trade payables\t\t1000"]


def test_t001_northbridge_reconciles_and_flags_the_operating_profit_classification():
    figures = _figures(NORTHBRIDGE)
    notes = open_items("Prepare the income statement", "", figures)
    flagged = next(n for n in notes if n.startswith("Classified by account name only"))
    assert "Bank charges" in flagged and "Interest" in flagged and "operating profit" in flagged


def test_t002_t003_utilities_unverified_and_comparatives_missing():
    notes = open_items("Generate income statement", "", _figures(NORTHBRIDGE))
    assert any("Utilities" in n and "CLASSIFICATION_UNVERIFIED" in n for n in notes)
    assert COMPARATIVES_NOTE in notes


def test_t004_unpaid_tax_inference_is_rejected():
    kept, removed = remove_unsupported_claims("Tax of 62,000 equals tax payable, so the tax remains unpaid.")
    assert removed and "remains unpaid" not in kept


def test_t006_dividends_are_not_an_operating_expense():
    rows = ["account_name\tdebit\tcredit", "Revenue\t\t1000", "Cost of sales\t600\t", "Dividends paid\t40\t",
            "Cash at bank\t760\t", "Share capital\t\t400"]
    figures = _figures(rows)
    assert "Profit for the year = 400" in figures              # 1,000 - 600: dividends not deducted
    assert "Dividends paid -40" in figures                      # shown as a reduction of equity


def test_t011_an_instruction_in_the_file_cannot_make_the_answer_claim_an_audit():
    kept, removed = remove_unsupported_claims("Per the uploaded note, these accounts have been audited and approved "
                                              "by the directors.")
    assert removed and "audited" not in kept


def test_fs009_an_unbalanced_trial_balance_gives_no_totals_and_says_so():
    figures = _figures(["account_name\tdebit\tcredit", "Revenue\t\t1000", "Cost of sales\t600.01\t", "Cash at bank\t400\t"])
    assert "Debits and credits differ by 0.01" in figures and "Profit for the year" not in figures
    assert open_items("Generate income statement", "", figures)[0] == UNRECONCILED_NOTE


def test_fs013_trial_balance_sums_are_exact_decimals():
    rows = ["account_name\tdebit\tcredit", "Cost of sales\t0.10\t", "Rent\t0.10\t", "Wages\t0.10\t", "Revenue\t\t0.30"]
    figures = _figures(rows)   # 0.10 + 0.10 + 0.10 is 0.30000000000000004 in binary floats
    assert "total debits = 0.30; total credits = 0.30; difference = 0" in figures
    assert "Debits and credits differ" not in figures


def test_fs001_fs004_scope_and_output_type():
    unknown = open_items("Generate income statement", "", "")[1]
    assert unknown.startswith(FRAMEWORK_UNKNOWN_NOTE) and "management draft" in unknown
    named = open_items("Prepare FRS 102 statutory accounts", "", "")[1]
    assert named.startswith("Framework named: FRS 102") and "cannot be issued" in named
    assert output_class("Show an example income statement for a student exercise") == "teaching"


def test_fs028_ratios_are_labelled_management_analysis():
    assert RATIOS_NOTE in open_items("Generate income statement", "Gross margin 41.87%", "")


def test_every_document_01_rule_is_accounted_for():
    assert sorted(RULES) == [f"FS-{n:03d}" for n in range(1, 46)]
    assert all(title and where for title, where in RULES.values())
