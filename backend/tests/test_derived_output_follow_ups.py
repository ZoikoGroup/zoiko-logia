"""Follow-ups that reshape cited rules (example, checklist, common mistakes,
a reviewer's version) can be answered: the rules stay cited and verified,
only a labelled example's hypothetical scenario is exempt."""
import pytest

from app.orchestration.derived_output import (
    ILLUSTRATION_HEADING, derived_output_instructions, is_derived_output_request, without_scenarios,
)
from app.orchestration.figure_reconciliation import unreconciled_figures
from app.orchestration.verification_service import release_claims
from app.orchestration.websearch import search_focus

EXAMPLE_ANSWER = f"""IFRS 18 supersedes IAS 1 [REF-1].

### {ILLUSTRATION_HEADING}
Alpha Ltd reports revenue of £4,200,000 and operating expenses of £3,100,000.
Its annual reporting period begins on 1 January 2027.
Alpha Ltd must present the operating profit subtotal required by IFRS 18 [REF-2].
The VAT rate on its sales is 20%.

### Checklist
- Check that the entity applies IFRS 18 for periods beginning on or after 1 January 2027 [REF-2].
"""


@pytest.mark.parametrize("query", [
    "Explain this with a grounded example. Context: the relationship between IFRS 18 and IAS 1",
    "Summarize this as a checklist. Context: the relationship between IFRS 18 and IAS 1",
    "Show common mistakes people make here. Context: IFRS 18",
    "Adapt this checklist for a reviewer role. Context: IFRS 18",
])
def test_follow_up_chips_are_derived_output_requests(query):
    assert is_derived_output_request(query)


def test_a_plain_question_is_not():
    assert not is_derived_output_request("What is the relationship between IFRS 18 and IAS 1?")


def test_instructions_require_citations_for_rules_but_not_the_scenario():
    text = derived_output_instructions()
    assert ILLUSTRATION_HEADING in text and "[REF-N]" in text
    assert "Never put a real rate or threshold in the scenario without its citation" in text


def test_scenario_sentences_are_not_claims_but_rules_inside_the_example_are():
    claims = release_claims(EXAMPLE_ANSWER)
    assert not any(claim.startswith("Alpha Ltd reports revenue") for claim in claims)
    assert not any(claim.startswith("Its annual reporting period") for claim in claims)
    assert any("operating profit subtotal" in claim for claim in claims)   # cited rule, still checked
    assert any("VAT rate on its sales is 20%" in claim for claim in claims)  # a real rate, still checked
    assert any("Check that the entity applies IFRS 18" in claim for claim in claims)
    assert any(claim.startswith("IFRS 18 supersedes IAS 1") for claim in claims)


def test_hypothetical_amounts_are_not_unsupported_figures_but_rates_are():
    evidence = "[REF-1] IFRS 18 supersedes IAS 1. [REF-2] Effective for periods beginning on or after 1 January 2027."
    unsupported = unreconciled_figures(EXAMPLE_ANSWER, evidence)
    assert not any("4,200,000" in figure or "3,100,000" in figure for figure in unsupported)
    # A rate inside the example stays in the figure check.
    assert "The VAT rate on its sales is 20%." in without_scenarios(EXAMPLE_ANSWER)
    assert unreconciled_figures(f"### {ILLUSTRATION_HEADING}\nThe VAT rate is 17.5%.", evidence) == ["17.5%"]


def test_the_same_amount_outside_an_example_is_still_checked():
    assert "Alpha Ltd reports revenue of £4,200,000" in without_scenarios(
        "### Background\nAlpha Ltd reports revenue of £4,200,000."
    )


def test_a_follow_up_chip_is_searched_by_its_topic():
    assert search_focus(
        "Summarize this as a checklist. Context: the relationship between IFRS 18 and IAS 1"
    ) == "the relationship between IFRS 18 and IAS 1"
    assert search_focus(
        "Explain this with a grounded example. Context: IFRS 18 and IAS 1"
        "\n\nPrevious user request for context: what is IFRS 18"
    ) == "IFRS 18 and IAS 1"


async def test_claim_batches_of_a_long_answer_are_judged_concurrently(monkeypatch):
    """Judged one batch after another, a long review spent most of the 105 s
    request deadline in verification and failed as "temporarily unavailable"."""
    import asyncio

    from app.orchestration import claim_verification, verification_service

    running, peak = 0, 0

    async def judge(claims, evidence, question=""):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return claim_verification.VerificationResult(
            checked=len(claims), supported=len(claims), ran=True,
            evidence_refs={i: ["REF-1"] for i in range(1, len(claims) + 1)},
        )

    monkeypatch.setattr(claim_verification, "enabled", lambda: True)
    monkeypatch.setattr(claim_verification, "verify_claims", judge)
    answer = "\n".join(f"IFRS 18 paragraph {i} requires presentation item number {i} [REF-1]." for i in range(48))
    result = await verification_service.verify_for_release(
        answer, question="IFRS 18", evidence=["[REF-1] IFRS 18 text"], requires_authority=True,
    )
    assert result.passed
    assert peak == verification_service._VERIFY_CONCURRENCY
