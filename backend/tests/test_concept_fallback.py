"""A concept question the sources do not cover gets a labelled general
explanation instead of "Not answered" (concept_fallback.py)."""
from unittest.mock import AsyncMock

from app.orchestration.concept_fallback import general_explanation, is_concept_question

FAILURE = "Kriton is temporarily unable to reach the language model provider."


def test_only_plain_concept_questions_qualify():
    plain = dict(has_documents=False, uses_live_data=False)
    assert is_concept_question("give me the difference between audit and account", **plain)
    assert is_concept_question("What is IPR?", **plain)
    assert is_concept_question("Explain accrual accounting", **plain)
    # figures, rules, live data or a file keep the sources-only answer
    assert not is_concept_question("What is the VAT registration threshold?", **plain)
    assert not is_concept_question("What is 18% of 50,000?", **plain)
    assert not is_concept_question("Explain the TDS rules for rent", **plain)
    assert not is_concept_question("What is audit?", has_documents=True, uses_live_data=False)
    assert not is_concept_question("What is the dollar rate?", has_documents=False, uses_live_data=True)
    assert not is_concept_question("Prepare a balance sheet", **plain)


def test_a_process_question_and_a_referral_after_the_gap_still_get_the_explanation():
    # QA case E02 got only "the sources do not contain this; consult your policies".
    from app.orchestration.verification_service import is_evidence_gap_statement, is_referral, release_claims

    plain = dict(has_documents=False, uses_live_data=False)
    assert is_concept_question("Show how a draft journal entry becomes an approved posted journal entry.", **plain)
    assert not is_concept_question("Show how a company becomes VAT registered in the UK.", **plain)
    gap = ("The sources retrieved do not contain information that establishes how a draft journal entry "
           "progresses to an approved posted journal entry. To answer this question you would need to consult "
           "an organization's accounting policies or internal control manuals.")
    assert is_evidence_gap_statement(gap)
    assert all(is_referral(claim) for claim in release_claims(gap))
    assert not is_referral("You would need to consult HMRC: the threshold is £90,000.")


async def test_a_concept_answer_that_ran_out_of_token_budget_gets_the_explanation(monkeypatch):
    # QA case E02 retest: the agent spent its budget reading search results
    # and the reader got only "No complete answer was generated".
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.domains.model_gateway.agent import AgentOutcome
    from app.orchestration import learned_answers, review, service
    from app.orchestration.concept_fallback import GENERAL_NOTE
    from app.orchestration.schemas import AskKritonRequest

    for name in dir(service):
        if name.startswith("audit_"):
            monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, "_finalise_and_return", AsyncMock())
    monkeypatch.setattr(service, "list_authorized_engagements", AsyncMock(return_value=[]))
    monkeypatch.setattr(review, "record_answer", AsyncMock())
    monkeypatch.setattr(learned_answers, "feedback_guidance", AsyncMock(return_value=""))
    monkeypatch.setattr(service, "build_source_bundle", AsyncMock(side_effect=RuntimeError("no governed library in tests")))
    monkeypatch.setattr(service, "web_search_each", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "select_prompt", AsyncMock(return_value=SimpleNamespace(
        id="prompt-test", mode="agent", template="{query}", version="1", model_hint=None)))
    monkeypatch.setattr(service, "classify_risk", AsyncMock(return_value="LOW"))
    monkeypatch.setattr(service, "classify_risk_gemini", AsyncMock(return_value=None))
    monkeypatch.setattr(service.model_gateway_service, "agent_mode_active", lambda: True)
    reason = "the configured token budget was reached"
    monkeypatch.setattr(service.model_gateway_service, "run_agentic_completion", AsyncMock(return_value=AgentOutcome(
        text=f"The full written answer could not be completed because {reason}. "
             "No complete answer was generated within that budget.",
        stop_reason="token_budget", incomplete_reason=reason)))
    explanation = ("A journal entry starts as a draft, is checked for balance and support, is approved by a "
                   "reviewer, and is then posted; a rejected entry goes back to draft.")
    monkeypatch.setattr(service.model_gateway_service, "run_grounded_completion", AsyncMock(return_value=explanation))
    response = await service.ask_kriton(AsyncMock(), MagicMock(), actor_id="u", tenant_id="t", role="ACCOUNTANT",
                                        request=AskKritonRequest(query="Show how a draft journal entry becomes an "
                                                                       "approved posted journal entry."))
    assert response.answer is not None and "goes back to draft" in response.answer.text
    assert GENERAL_NOTE in response.answer.limitations
    assert not any("budget was reached" in note for note in response.answer.limitations)


async def test_the_explanation_is_used_only_without_figures_or_citations():
    good = "Accounting records and reports transactions; an audit independently examines those records."
    assert await general_explanation("audit vs accounting", AsyncMock(return_value=good), FAILURE) == good
    for bad in ("The audit threshold is £10,200,000.", "Under section 143 an audit…", "Audit is done [REF-1].",
                "VAT is 20% in the UK.", FAILURE, "ok"):
        assert await general_explanation("q", AsyncMock(return_value=bad), FAILURE) == ""
    assert await general_explanation("q", AsyncMock(side_effect=RuntimeError("down")), FAILURE) == ""
