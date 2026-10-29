"""Accounting treatment checks (accounting_validation.py), independent of the
arithmetic check: a grounded VAT example passed every arithmetic check with
the accounting wrong (24 Oct 2026). Each rule has a wrong case it must flag
and a right case it must leave alone; a finding is disclosed and audited,
never rewritten. No model, database or network.
"""
import inspect

import pytest

from app.orchestration import audit_events, service
from app.orchestration.accounting_validation import REVIEW_PREFIX, accounting_findings, accounting_review_note
from app.orchestration.calculation_service import validate_answer_calculations

# The answer reviewed on 24 Oct 2026, as released.
RELEASED = """Entity: GreenTech Ltd. Turnover: £950 000 (VAT‑taxable). Cost of goods sold: £600 000 (includes £50 000 of VAT‑inclusive purchases).

| Item | Calculation | Result | Tax rule cited |
|---|---|---|---|
| VAT output tax | Turnover × 20 % | £950 000 × 0.20 = £190 000 | VAT output tax is the VAT due on taxable supplies |
| VAT input tax | VAT on purchases (excluding VAT‑exclusive expenses) | £50 000 | Input tax is the VAT paid on purchases |
| VAT payable | Output – Input | £190 000 – £50 000 = £140 000 | Net VAT payable is output minus input |
| Total tax burden | VAT payable + Corporate tax | £140 000 + £28 500 = £168 500 | Combined tax liability for the year |

| Date | Account | Debit | Credit |
|---|---|---|---|
| 31 Dec 2025 | VAT payable | £140 000 | – |
| 31 Dec 2025 | Corporate tax expense | £28 500 | – |
| 31 Dec 2025 | Cash/Bank | – | £168 500 |
"""


def rules(text):
    return sorted(finding.rule for finding in accounting_findings(text))


def test_the_released_example_passes_arithmetic_but_not_treatment():
    assert validate_answer_calculations(RELEASED) == []          # every figure adds up, the entry balances
    assert rules(RELEASED) == ["collected_tax_as_cost", "tax_equals_inclusive_amount", "tax_expense_on_payment"]


def journal(*rows):
    return "| Account | Debit | Credit |\n|---|---|---|\n" + "\n".join(f"| {a} | {d} | {c} |" for a, d, c in rows)


@pytest.mark.parametrize("wrong, right, rule", [
    (journal(("Corporation tax expense", "£28,500", ""), ("Cash", "", "£28,500")),
     journal(("Corporation tax expense", "£28,500", ""), ("Corporation tax payable", "", "£28,500")),
     "tax_expense_on_payment"),
    (journal(("Sales", "£1,000", ""), ("Cash", "", "£1,000")),
     journal(("Cash", "£1,000", ""), ("Sales", "", "£1,000")),
     "revenue_debited"),
    (journal(("Cash", "£1,200", ""), ("Output VAT", "£200", ""), ("Sales", "", "£1,400")),
     journal(("Cash", "£1,200", ""), ("Sales", "", "£1,000"), ("Output VAT", "", "£200")),
     "output_tax_debited"),
    (journal(("Purchases", "£500", ""), ("Input VAT", "", "£100"), ("Cash", "", "£400")),
     journal(("Purchases", "£500", ""), ("Input VAT", "£100", ""), ("Cash", "", "£600")),
     "input_tax_credited"),
    ("Purchases: £60,000 (VAT-inclusive). Input VAT: £60,000.",
     "Purchases: £60,000 (VAT-inclusive). Input VAT = £60,000 × 20/120 = £10,000.",
     "tax_equals_inclusive_amount"),
    ("Total tax burden = VAT payable + corporation tax = £14,000 + £28,500 = £42,500.",
     "Total tax cost: corporation tax of £28,500; the VAT of £14,000 is collected for HMRC.",
     "collected_tax_as_cost"),
    ("Under IFRS 16, an operating lease gives the lessee a single straight-line lease expense.",
     "Under IFRS 16 the lessee depreciates the right-of-use asset; unlike ASC 842 there is no single straight-line "
     "operating lease expense.",
     "ifrs16_lessee_operating_lease"),
    ("Basic EPS = $2.11. Diluted EPS = $2.37.", "Basic EPS = $2.11. Diluted EPS = $2.00.", "diluted_eps_above_basic"),
])
def test_each_rule_flags_the_wrong_case_and_not_the_right_one(wrong, right, rule):
    assert rule in rules(wrong)
    assert rule not in rules(right)


@pytest.mark.parametrize("text", [
    journal(("Sales returns", "£1,000", ""), ("Cash", "", "£1,000")),          # a return reverses a sale
    journal(("Rent expense", "£2,000", ""), ("Cash", "", "£2,000")),           # an expense paid in cash
    journal(("Corporation tax payable", "£28,500", ""), ("Cash", "", "£28,500")),  # paying the liability
    "The VAT rate is 20%.",
    "Input VAT is the VAT a business pays on its purchases.",
])
def test_ordinary_correct_answers_are_not_flagged(text):
    assert rules(text) == []


def test_the_note_says_the_arithmetic_is_not_the_treatment():
    note = accounting_review_note(accounting_findings(RELEASED))
    assert note.startswith(f"{REVIEW_PREFIX}: the figures add up, but the treatment should be checked")
    assert "one-sixth" in note and "not the business's cost" in note and "clears the payable" in note
    assert accounting_review_note([]) is None


def test_every_released_answer_is_checked_and_audited_not_rewritten():
    source = inspect.getsource(service.ask_kriton)
    start = source.index("treatment = accounting_findings(response.answer.text or '')")
    assert "accounting_review = treatment + mismatches" in source
    assert "'limitations': [*response.answer.limitations, *notes]" in source
    assert "findings=accounting_review_entries(accounting_review)" in source
    assert "'text':" not in source[start:source.index("response.answer = response.answer.model_copy(update={'completeness': 'partial'})")]


def test_the_audit_keeps_a_hash_and_a_redacted_excerpt():
    entries = service.accounting_review_entries(accounting_findings(RELEASED))
    assert {entry["rule"] for entry in entries} == set(rules(RELEASED))
    assert all(set(entry) == {"rule", "statement_hash", "excerpt"} for entry in entries)


async def test_the_audit_event(monkeypatch):
    emitted = []

    async def emit(db, name, *args, **kwargs):
        emitted.append((name, args[-1], kwargs))
    monkeypatch.setattr(audit_events, "_emit", emit)
    await audit_events.audit_accounting_review_flagged(
        None, query_id="q", correlation_id="c", tenant_id="t", audit_chain_id="a", actor_id="u",
        findings=[{"rule": "revenue_debited", "statement_hash": "h", "excerpt": "Sales"}])
    assert emitted[0][0] == "accounting_review_flagged" and emitted[0][1]["rules_version"] == "1"
    assert emitted[0][2]["replay_relevance"] == "REQUIRED"


# ── Through the real pipeline ─────────────────────────────────────────────

from tests.test_answer_status_pipeline import page_status, pipeline  # noqa: E402,F401
from app.domains.model_gateway.agent import AgentOutcome  # noqa: E402


SALE = "We sold goods for £1,000 in cash. Show the journal entry."


async def test_a_treatment_finding_is_not_shown_as_fully_answered(pipeline):
    pipeline.answers(AgentOutcome(text="Record the cash sale like this:\n\n"
                                       + journal(("Sales", "£1,000", ""), ("Cash", "", "£1,000"))))
    response, audited = await pipeline.ask(SALE)
    assert any(item.startswith(REVIEW_PREFIX) for item in response.answer.limitations)
    assert page_status(response) == "Partially answered" and audited.completeness == "partial"
    assert "| Sales | £1,000 |" in response.answer.text                 # disclosed, not rewritten
    assert service.audit_accounting_review_flagged.await_args.kwargs["findings"][0]["rule"] == "revenue_debited"


async def test_the_right_entry_is_released_without_a_treatment_note(pipeline):
    pipeline.answers(AgentOutcome(text="Record the cash sale like this:\n\n"
                                       + journal(("Cash", "£1,000", ""), ("Sales", "", "£1,000"))))
    response, audited = await pipeline.ask(SALE)
    assert not any(item.startswith(REVIEW_PREFIX) for item in response.answer.limitations)
    assert not service.audit_accounting_review_flagged.await_args_list
