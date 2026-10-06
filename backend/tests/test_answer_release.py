from unittest.mock import AsyncMock
import pytest
from app.orchestration import claim_verification as cv
from app.orchestration.verification_service import (
    normalize_citations, prune_rejected_claims, verify_for_release, release_claims, requires_authoritative_evidence,
)


def test_fullwidth_citations_become_canonical_and_count_as_cited():
    # Live draft escalated as "a factual claim lacks a valid citation".
    answer = normalize_citations(
        "The UK VAT registration threshold is £90,000 of taxable turnover【REF-8】【REF-6】", {"REF-6", "REF-8"},
    )
    assert answer == "The UK VAT registration threshold is £90,000 of taxable turnover[REF-8][REF-6]"
    assert release_claims(answer) == [answer]
    assert normalize_citations("Below the threshold [REF‑8].", {"REF-8"}) == "Below the threshold [REF-8]."


def test_invented_references_are_dropped_and_real_ones_kept():
    # Live draft escalated as "Citation binding failed: [REF-16]" with 8 sources.
    answer = normalize_citations(
        "A business can deregister when turnover falls below £88,000 [REF-1][REF-3][ref 4][REF-16].",
        {f"REF-{n}" for n in range(1, 9)},
    )
    assert answer == "A business can deregister when turnover falls below £88,000 [REF-1][REF-3][REF-4]."


@pytest.mark.parametrize("query", ["Who can file a VAT return?", "When must I leave cash accounting?", "Explain IFRS 16", "What is the tax rate?"])
def test_qualitative_regulatory_questions_require_authority(query):
    assert requires_authoritative_evidence(query)


async def test_required_verification_disabled_or_missing_evidence_goes_to_review(monkeypatch):
    monkeypatch.setenv("CLAIM_VERIFICATION", "off")
    result = await verify_for_release("The rate is 20%.", question="UK VAT rate?", evidence=["20%"], requires_authority=True)
    assert not result.passed
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    assert not (await verify_for_release("The rate is 20%.", question="UK VAT rate?", evidence=[], requires_authority=True)).passed


@pytest.mark.parametrize("verdict", [cv.VerificationResult(), cv.VerificationResult(checked=2, supported=1, ran=True), cv.VerificationResult(checked=1, not_in_evidence=1, ran=True)])
async def test_unavailable_partial_and_unsupported_verdicts_fail_closed(monkeypatch, verdict):
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    monkeypatch.setattr(cv, "verify_claims", AsyncMock(return_value=verdict))
    assert not (await verify_for_release("Agents can submit authorised VAT returns. [REF-1]", question="VAT filing?", evidence=["[REF-1] Agent guidance"], requires_authority=True)).passed


async def test_verified_qualitative_claim_can_pass(monkeypatch):
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    verifier = AsyncMock(return_value=cv.VerificationResult(checked=1, supported=1, ran=True, evidence_refs={1: ["REF-1"]}))
    monkeypatch.setattr(cv, "verify_claims", verifier)
    answer = "An authorised agent can submit a VAT return. [REF-1]"
    assert (await verify_for_release(answer, question="Who can file?", evidence=["[REF-1] An authorised agent can submit."], requires_authority=True)).passed
    assert verifier.await_args.args[0]  # qualitative prose was actually submitted


async def test_self_contained_calculation_does_not_require_a_model_judge():
    assert (await verify_for_release("Gross profit is £90,000.", question="250000 - 160000?", evidence=[], requires_authority=False)).passed


def test_long_claims_and_claims_beyond_the_cap_are_not_silently_ignored():
    assert len(release_claims("A" * 500)) == 1
    assert len(release_claims("\n".join(f"Rule number {i} applies to VAT returns." for i in range(14)))) == 14

async def test_supported_claim_with_wrong_citation_cannot_pass(monkeypatch):
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    monkeypatch.setattr(cv, "verify_claims", AsyncMock(return_value=cv.VerificationResult(
        checked=1, supported=1, ran=True, evidence_refs={1: ["REF-2"]})))
    assert not (await verify_for_release("VAT is 20%. [REF-1]", question="VAT rate?",
        evidence=["[REF-1] Registration rules", "[REF-2] VAT is 20%."], requires_authority=True)).passed


async def test_all_claim_batches_must_pass(monkeypatch):
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    verifier = AsyncMock(side_effect=[
        cv.VerificationResult(checked=12, supported=12, ran=True, evidence_refs={i: ["REF-1"] for i in range(1, 13)}),
        cv.VerificationResult(checked=1, not_in_evidence=1, ran=True),
    ])
    monkeypatch.setattr(cv, "verify_claims", verifier)
    answer = "\n".join(f"Rule number {i} applies to this VAT return. [REF-1]" for i in range(13))
    assert not (await verify_for_release(answer, question="VAT rules?", evidence=["[REF-1] Rules"], requires_authority=True)).passed
    assert verifier.await_count == 2


def test_table_headers_are_structure_but_data_rows_are_claims():
    assert release_claims('| Scheme | Leave above |\n| --- | --- |\n| Flat Rate Scheme | £230,000 [REF-1] |') == ['| Flat Rate Scheme | £230,000 [REF-1] |']


def test_a_list_introduction_is_structure_not_an_uncited_claim():
    answer = (
        "For the Annual Accounting Scheme the deadlines differ:\n"
        "- A 4 to 12 month period is due 2 months after it ends [REF-8]."
    )
    assert release_claims(answer) == ["A 4 to 12 month period is due 2 months after it ends [REF-8]."]


async def test_uncited_and_unsupported_claims_are_reported_for_removal(monkeypatch):
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    monkeypatch.setattr(cv, "verify_claims", AsyncMock(return_value=cv.VerificationResult(
        checked=2, supported=1, not_in_evidence=1, ran=True, evidence_refs={1: ["REF-1"]}, rejected_ids=[2])))
    answer = (
        "Children's clothing is zero-rated [REF-1]. It must be designed for young children [REF-1].\n"
        "Otherwise the standard 20% rate applies."
    )
    result = await verify_for_release(answer, question="VAT on children's clothes?",
                                      evidence=["[REF-1] Children's clothing is zero-rated."], requires_authority=True)
    assert not result.passed and result.prunable
    assert result.rejected_claims == [
        "Otherwise the standard 20% rate applies.", "It must be designed for young children [REF-1].",
    ]
    assert prune_rejected_claims(answer, result.rejected_claims) == "Children's clothing is zero-rated [REF-1]."


async def test_an_unavailable_verifier_is_never_prunable(monkeypatch):
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    monkeypatch.setattr(cv, "verify_claims", AsyncMock(return_value=cv.VerificationResult()))
    result = await verify_for_release("VAT is 20% [REF-1]. Also uncited filler here.", question="VAT rate?",
                                      evidence=["[REF-1] VAT is 20%."], requires_authority=True)
    assert not result.passed and not result.prunable


async def test_nothing_supported_is_not_prunable(monkeypatch):
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    result = await verify_for_release("This sentence has no citation at all.", question="VAT rate?",
                                      evidence=["[REF-1] VAT is 20%."], requires_authority=True)
    assert not result.passed and not result.prunable


def test_headings_and_restated_questions_in_a_multi_question_answer_are_not_claims():
    # Live draft: these headings were pruned as uncited, leaving bare "****".
    answer = (
        "**UK VAT registration threshold**\n\n"
        "- The current registration threshold is £90,000 of taxable turnover [REF-9].\n\n"
        "**Is the VAT threshold £85,000?**\n\n"
        "- It was £85,000 for 2022-23 but has since risen to £90,000 [REF-4][REF-9].\n"
    )
    assert release_claims(answer) == [
        "The current registration threshold is £90,000 of taxable turnover [REF-9].",
        "It was £85,000 for 2022-23 but has since risen to £90,000 [REF-4][REF-9].",
    ]


@pytest.mark.parametrize("text, is_gap", [
    ("The sources provided do not state this.", True),
    ("| India (GST) | The sources provided do not state this. |", True),
    ("The retrieved guidance doesn't specify the India threshold.", True),
    ("This is not stated in the provided sources.", True),
    # A gap caveat that still carries a figure is an unsourced claim.
    ("No figure in the provided sources does not state it, but generally it is ₹40 lakh.", False),
    ("The sources do not state it; it is usually 20%.", False),
    ("VAT is charged at 20% on most goods.", False),
])
def test_only_figure_free_evidence_gap_statements_are_exempt(text, is_gap):
    from app.orchestration.verification_service import is_evidence_gap_statement
    assert is_evidence_gap_statement(text) is is_gap
    assert (release_claims(text) == []) is is_gap


def test_a_heading_left_empty_by_pruning_is_acknowledged_not_blank():
    answer = (
        "**VAT threshold in the UK**\n\n- The threshold is £85,000 [REF-4].\n\n"
        "**Standard rate**\nThe standard rate is 20% [REF-1]."
    )
    pruned = prune_rejected_claims(answer, ["The threshold is £85,000 [REF-4]."])
    assert pruned.splitlines()[:2] == ["**VAT threshold in the UK**", "The sources provided do not confirm this."]
    assert "The standard rate is 20% [REF-1]." in pruned
    assert release_claims(pruned) == ["The standard rate is 20% [REF-1]."]


def test_placeholder_references_are_dropped():
    assert normalize_citations(
        "The sources provided do not state the GST thresholds for India. [REF‑none]", {"REF-1"},
    ) == "The sources provided do not state the GST thresholds for India."


async def test_an_answer_that_only_reports_missing_evidence_is_released(monkeypatch):
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    result = await verify_for_release("The sources provided do not state this.", question="Singapore GST rate?",
                                      evidence=["[REF-1] Unrelated passage."], requires_authority=True)
    assert result.passed
    assert not (await verify_for_release("Here is some general guidance.", question="Singapore GST rate?",
                                         evidence=["[REF-1] Unrelated passage."], requires_authority=True)).passed


@pytest.mark.parametrize("query, dangling", [
    ("Start a new chat: Increase those expenses by 10% and recalculate.", True),
    ("Chart the above figures", True),
    ("Increase those expenses of 5,000 by 10%", False),
    ("What is this VAT rule?", False),
])
def test_references_to_earlier_figures_are_detected(query, dangling):
    from app.orchestration.service import dangling_reference
    assert dangling_reference(query) is dangling


def test_invented_markers_are_removed():
    assert normalize_citations("Profit is -₹15,000【CALC-1】 [REF-1].", {"REF-1"}) == "Profit is -₹15,000 [REF-1]."


@pytest.mark.parametrize("line, exempt", [
    ("Current ratio = 2,50,000 ÷ 1,00,000 = 2.50", True),
    ("Markup = (£100 − £80) ÷ £80 × 100 = 25%", True),
    ("The standard rate is 20%, so VAT = £1,000 × 20% = £200", False),
    ("The VAT threshold is £90,000.", False),
])
def test_only_pure_arithmetic_on_supplied_figures_needs_no_citation(line, exempt):
    assert (release_claims(line) == []) is exempt


async def test_an_answer_of_only_supplied_figure_arithmetic_is_released(monkeypatch):
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    answer = "**Break-even**\nBreak-even units = 50,000 ÷ 10 = 5,000 units"
    assert (await verify_for_release(answer, question="Break-even? Also CAGR?",
                                     evidence=["[REF-1] x"], requires_authority=True)).passed


def test_an_inline_heading_survives_removal_of_its_answer():
    # Live: removing part 5's answer left a bare "**5." in the reply.
    answer = (
        "**5. TDS on rent of a building in India** – TDS is 10% under section 194-I [REF-9].\n\n"
        "**3. UK personal allowance** – The personal allowance is £12,570 [REF-4]."
    )
    from app.orchestration.verification_service import _release_claim_pairs
    claims = [original for original, _ in _release_claim_pairs(answer)]
    assert claims == ["TDS is 10% under section 194-I [REF-9].", "The personal allowance is £12,570 [REF-4]."]
    # Checked with its heading, so the verifier knows what the figure answers.
    assert release_claims(answer)[0].startswith("5. TDS on rent of a building in India: ")
    pruned = prune_rejected_claims(answer, [claims[0]])
    assert pruned.splitlines()[0] == "**5. TDS on rent of a building in India** – The sources provided do not confirm this."
    assert [original for original, _ in _release_claim_pairs(pruned)] == [claims[1]]


def test_a_bare_figure_under_a_heading_is_checked_with_that_heading():
    from app.orchestration.verification_service import _release_claim_pairs
    answer = "**UK corporation tax rate for £300,000 profit**\n30 % [REF-1]"
    assert _release_claim_pairs(answer) == [
        ("30 % [REF-1]", "UK corporation tax rate for £300,000 profit: 30 % [REF-1]"),
    ]


def test_calculation_tags_keep_their_figure():
    assert normalize_citations("Income tax at 20% [calculate result £6,486].", set()) == "Income tax at 20% £6,486."
    assert normalize_citations("VAT is £200 [calculated].", set()) == "VAT is £200 ."


def test_removing_a_bulleted_sentence_removes_its_bullet():
    answer = "- Goods: 4 years [REF-1]\n- Services: 6 months [REF-2]\n---\n- Kept line [REF-3]"
    assert cv.remove_claims(answer, ["Goods: 4 years [REF-1]"]) == "- Services: 6 months [REF-2]\n---\n- Kept line [REF-3]"


async def test_a_contradiction_is_removed_only_when_confirmed(monkeypatch):
    from app.orchestration import verification_service as vs
    monkeypatch.setenv("CLAIM_VERIFICATION", "on")
    claim = "Goods bought up to 4 years before registration qualify [REF-1]."
    contradicted = cv.VerificationResult(checked=1, ran=True, contradicted=[cv.Contradiction(claim, "different")], rejected_ids=[1])
    supported = cv.VerificationResult(checked=1, supported=1, ran=True, evidence_refs={1: ["REF-1"]})
    # First verdict and the post-correction recheck both say contradicted;
    # the confirming check does not, so the correct sentence is kept.
    monkeypatch.setattr(cv, "verify_claims", AsyncMock(side_effect=[contradicted, contradicted, supported]))
    monkeypatch.setattr(vs.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=claim))

    class _Metrics:
        async def run(self, _name, awaitable):
            return await awaitable
    text, note = await vs._verify_answer_claims(
        claim, evidence=["[REF-1] Goods: 4 years."], question="How far back?", grounded_input="",
        report=AsyncMock(), metrics=_Metrics(),
    )
    assert text == claim and note is None


def test_parenthesised_citations_are_normalised():
    assert normalize_citations("VAT is £200 (REF‑7).", {"REF-7"}) == "VAT is £200 [REF-7]."


def test_failed_release_check_escalates_only_high_risk():
    from app.orchestration.verification_service import AnswerVerification, decide_release_failure
    answer = "The threshold is £90,000 [REF-1].\nYou will definitely be fined £5,000."
    check = AnswerVerification(False, ["unsupported"], rejected_claims=["You will definitely be fined £5,000."])
    # High risk (the asker's own matter) still goes to a human reviewer.
    assert decide_release_failure(answer, check, risk_level="HIGH", validation_passed=True).escalate
    # So does an answer that already failed another validation (e.g. arithmetic).
    assert decide_release_failure(answer, check, risk_level="LOW", validation_passed=False).escalate
    # Otherwise the unverified sentence is removed and the rest released, flagged.
    released = decide_release_failure(answer, check, risk_level="MEDIUM", validation_passed=True)
    assert not released.escalate and "fined" not in released.text and "£90,000" in released.text
    assert released.note and "could not verify" in released.note


def test_nothing_verifiable_left_becomes_an_honest_gap_and_unavailable_checker_is_flagged():
    from app.orchestration.verification_service import AnswerVerification, decide_release_failure
    only_bad = AnswerVerification(False, ["unsupported"], rejected_claims=["The rate is 25% from 2027."])
    result = decide_release_failure("The rate is 25% from 2027.", only_bad, risk_level="LOW", validation_passed=True)
    assert result.text == "The sources provided do not establish an answer to this."
    unavailable = AnswerVerification(False, ["Claim verification unavailable or incomplete"])
    kept = decide_release_failure("The threshold is £90,000 [REF-1].", unavailable, risk_level="LOW", validation_passed=True)
    assert not kept.escalate and kept.text.startswith("The threshold") and "unverified" in kept.note
