"""Pasted case studies (29 Oct 2026 live test: Apex Motors, Zenith Retail,
NovaTech, Vanguard Infrastructure).

1. Checks written for one short question read a case's background as the
   request: "GST" and "deferred tax asset/liability" asked a VAT question;
   "Apex Motors" and "net profit" fetched an unrelated US company's SEC
   filing; "auditing the financial statements" added draft-statement notes;
   the countries named added "standard tax rates could not be verified".
2. A background pasted with no question was answered with a VAT question.
3. Searches were the background paragraphs ("Zenith recorded online sales
   revenue on the date an order was placed…"); nothing official matched and
   the whole answer was withheld.
4. Gaps about law were filled with invented "general explanation": "the
   domestic Act generally prevails unless the DTAA expressly overrides it"
   (Section 90(2) applies the more beneficial) and made-up stay conditions.
No model, database or network.
"""
import pytest

from app.domains.market_data.registry import detect_intent
from app.orchestration import evidence_planning
from app.orchestration.case_text import request_part
from app.orchestration.gap_filler import explanation_gaps, fill_explanation_gaps
from app.orchestration.input_requirements import (
    STATEMENT_CLARIFICATION, missing_vat_inputs, statement_not_question, tax_rate_comparison_gaps,
)
from app.orchestration.statement_rules import is_statement_request
from app.orchestration.websearch import evidence_search_queries

BACKGROUND = (
    "Apex Motors Ltd. is a mid-sized manufacturing company registered under GST in Telangana. For the financial year "
    "ended March 31, 2026, the company reported a turnover of ₹18.5 Crores. During the year, Apex Motors undertook a "
    "major capital expansion by importing heavy machinery from Germany worth €1.2 Million and setting up a new "
    "production line.\nWhile auditing the financial statements and tax filings, you (the statutory/tax auditor) "
    "uncover the following anomalies:\n"
    "1. Capitalization vs. Revenue Expenditure: Apex Motors booked ₹45 Lakhs related to trial runs, site preparation, "
    "and foreign technician fees as a routine revenue expense in the Profit & Loss statement to lower its net taxable "
    "income.\n"
    "2. GST Input Tax Credit (ITC) Discrepancy: The company claimed full Input Tax Credit (ITC) of ₹22 Lakhs on a "
    "commercial passenger vehicle bought in the company's name for the managing director's personal and official use.\n"
    "3. Deferred Tax & Depreciation: For corporate income tax purposes, the company claimed depreciation under the "
    "Written Down Value (WDV) method at standard rates, but for internal management reporting (Ind AS compliance), it "
    "used the Straight-Line Method (SLM), creating a massive temporary difference. No deferred tax asset/liability was "
    "adjusted in Q3 or Q4.\n"
    "4. Related Party Transaction / Transfer Pricing: Apex Motors sold finished components to a subsidiary in UAE at a "
    "25% discount compared to its domestic market price, without maintaining a local transfer pricing study."
)
QUESTIONS = (
    "• Q1.1 (Tax & Accounting Treatment): Analyze the ₹45 Lakhs booked as revenue expenditure. Under the Income Tax "
    "Act, 1961 (and Ind AS/GAAP), how should this be treated? Calculate the impact on net profit and tax liability.\n"
    "• Q1.2 (GST Audit): Evaluate the ITC claims. Is the company eligible for ITC on the passenger vehicle?\n"
    "• Q1.3 (Financial Reporting / Deferred Tax): Explain how the divergence between WDV depreciation and SLM "
    "depreciation creates a temporary difference. Pass the necessary journal entry.\n"
    "• Q1.4 (Auditor's Duty & Reporting): What observations must you record in the Tax Audit Report (Form 3CD)?"
)
CASE = f"The Manufacturing Expansion & Tax Audit Dilemma\n\nThe Background:\n\n{BACKGROUND}\n\nQuestions to Answer:\n\n{QUESTIONS}"


# 1 ----------------------------------------------------------------------------

@pytest.mark.parametrize("heading", ["Questions to Answer:", "Task for the Bot:", "Required:", "**Questions**"])
def test_the_request_part_is_what_follows_the_question_heading(heading):
    assert request_part(f"Background with GST.\n\n{heading}\n1. Explain Ind AS 115.") == "1. Explain Ind AS 115."


def test_an_ordinary_question_is_unchanged():
    question = "UK company, VAT at 20%: sales £100,000, purchases £50,000. Calculate VAT payable."
    assert request_part(question) == question


def test_the_background_no_longer_drives_the_question_checks():
    assert detect_intent(CASE) is None                    # no SEC filing for "Apex Motors … net profit"
    assert not is_statement_request(CASE)                 # "auditing the financial statements" is background
    assert tax_rate_comparison_gaps(CASE, "") == []       # India, Germany and UAE are only named
    assert missing_vat_inputs(CASE, []) is None


def test_a_vat_amount_is_still_asked_about_in_one_sentence():
    assert missing_vat_inputs("UK company, VAT at 20%: sales £100,000, purchases £50,000. Calculate VAT payable.", [])
    assert missing_vat_inputs("UK business: sales £100,000. How much VAT do I owe?", [])


# 2 ----------------------------------------------------------------------------

def test_a_background_with_no_question_asks_what_to_do():
    assert missing_vat_inputs(BACKGROUND, []) is None     # "GST" and "liability" are in different sentences
    assert statement_not_question(BACKGROUND) == STATEMENT_CLARIFICATION


def test_a_short_message_with_the_users_own_figures_is_still_not_a_statement():
    assert statement_not_question("My revenue is ₹500,000 for the year.") is None


# 3 ----------------------------------------------------------------------------

def test_a_case_is_searched_by_its_questions_not_its_background():
    queries = evidence_search_queries(request_part(CASE))
    assert len(queries) == 4 and all(query.startswith("Q1.") for query in queries)
    assert not any("Apex Motors booked" in query for query in queries)


async def test_a_long_request_gets_longer_to_plan(monkeypatch):
    seen = {}

    async def complete(**kwargs):
        seen["timeout"] = kwargs["timeout"]
        raise TimeoutError

    monkeypatch.setenv("EVIDENCE_PLANNING", "on")
    monkeypatch.setattr(evidence_planning.gateway, "may_use", lambda *args: True)
    monkeypatch.setattr(evidence_planning.gateway, "complete_auxiliary", complete)
    await evidence_planning.plan_evidence_search(CASE, ["Ind AS 115 revenue", "Section 41(1) remission"])
    assert seen["timeout"] == evidence_planning._LONG_TIMEOUT
    await evidence_planning.plan_evidence_search("What is Ind AS 115?", ["Ind AS 115 revenue"])
    assert seen["timeout"] == evidence_planning._TIMEOUT


# 4 ----------------------------------------------------------------------------

def test_a_gap_about_law_is_not_filled():
    text = ("Q3.1: The sources do not state which provision prevails between the Act and the treaty.\n"
            "Q3.3: The sources do not state the conditions for a stay of demand at the first appeal.\n"
            "The sources do not state the factors that determine the useful life of equipment.")
    assert explanation_gaps(text) == ["The sources do not state the factors that determine the useful life of equipment."]


async def test_an_explanation_stating_a_rule_of_law_is_discarded():
    text = "The sources do not state why entities defer revenue."

    async def complete(_prompt):
        return "1. The domestic Act generally prevails unless the treaty expressly overrides it."
    kept, filled = await fill_explanation_gaps(text, "Explain deferral", complete, "PROVIDER FAILURE")
    assert not filled and kept == text

    async def accounting(_prompt):
        return "1. Revenue is deferred until the goods or services are delivered to the customer."
    kept, filled = await fill_explanation_gaps(text, "Explain deferral", accounting, "PROVIDER FAILURE")
    assert filled and "General explanation:" in kept


CLOUDLEDGER = (
    "CloudLedger Ltd – Quarter-End Review\n\nThe Background:\n\nCloudLedger Ltd is a UK software company registered "
    "for VAT. For the quarter ended 30 September 2026 it made standard-rated sales of £240,000 and standard-rated "
    "purchases of £90,000; all figures exclude VAT and VAT is 20%.\n\nQuestions to Answer:\n\n"
    "• Q1 (VAT): Calculate the VAT payable for the quarter.\n• Q2 (IFRS 15): Allocate the £120,000 transaction price."
)


def test_a_case_vat_question_reads_its_facts_from_the_background():
    # The questions say a VAT amount is wanted; the background gives the
    # country, the rate, that the figures exclude VAT and that both are
    # standard-rated. Read from the questions alone they were asked for.
    assert missing_vat_inputs(CLOUDLEDGER, []) is None
    assert missing_vat_inputs(CLOUDLEDGER.replace("all figures exclude VAT and ", ""), [])  # treatment really missing
