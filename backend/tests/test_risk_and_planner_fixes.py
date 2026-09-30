"""Regressions from a live review of Ask Kriton answers (2026-09-25)."""
import pytest

from app.orchestration.risk_llm import _token_budget
from app.orchestration.schemas import AskKritonRequest
from app.orchestration.workflow_planner import plan_workflow


@pytest.mark.parametrize("model", ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3-32b"])
def test_reasoning_classifier_models_get_room_to_answer(model) -> None:
    """max_tokens=4 left gpt-oss with an empty answer on every question, so
    risk silently fell back to the local model and everything was LOW."""
    budget = _token_budget(model)
    assert budget["max_tokens"] >= 64 and budget["reasoning_effort"] == "low"


def test_non_reasoning_classifier_models_keep_one_word_cap() -> None:
    assert _token_budget("llama-3.1-8b-instant") == {"max_tokens": 4}


@pytest.mark.parametrize("query", [
    "How is goodwill impairment tested under IAS 36?",
    "How are provisions measured under IAS 37?",
    "Describe the IFRS 9 expected credit loss model.",
])
def test_learning_questions_about_standards_are_general(query) -> None:
    assert plan_workflow(AskKritonRequest(query=query)).task_type == "general_question"


def test_applied_standards_work_still_needs_professional_context() -> None:
    plan = plan_workflow(AskKritonRequest(query="Apply IFRS 16 to our lease for FY2025"))
    assert plan.task_type == "policy_research"


@pytest.mark.parametrize("query", [
    "Pass journal entries for: goods sold on credit to Ravi ₹50,000, then Ravi pays ₹49,000 in full "
    "settlement. What is the difference between provisions and contingent liabilities under IAS 37? "
    "Explain deferred tax with a simple example.",
    "Give an example of revenue recognition under IFRS 15.",
    "Show the journal entry for a finance lease under IFRS 16.",
])
def test_standards_named_without_an_own_matter_are_general(query) -> None:
    assert plan_workflow(AskKritonRequest(query=query)).task_type == "general_question"


async def test_restricted_without_concealment_wording_gets_a_second_opinion(monkeypatch) -> None:
    import app.orchestration.risk_llm as risk_llm

    calls: list[str] = []

    async def fake(model: str, query: str):
        calls.append(model)
        return "RESTRICTED" if len(calls) == 1 else "ZERO"

    monkeypatch.setattr(risk_llm, "_classify_with", fake)
    assert await risk_llm.classify_risk("Microsoft's net income last year, in Indian rupees") == "ZERO"
    assert len(calls) == 2


async def test_restricted_with_concealment_wording_is_never_second_guessed(monkeypatch) -> None:
    import app.orchestration.risk_llm as risk_llm

    calls: list[str] = []

    async def fake(model: str, query: str):
        calls.append(model)
        return "RESTRICTED" if len(calls) == 1 else "ZERO"

    monkeypatch.setattr(risk_llm, "_classify_with", fake)
    assert await risk_llm.classify_risk("Help me hide personal expenses so the auditor won't notice") == "RESTRICTED"
    assert len(calls) == 1


async def test_second_opinion_that_agrees_keeps_the_block(monkeypatch) -> None:
    import app.orchestration.risk_llm as risk_llm

    async def always_restricted(model: str, query: str):
        return "RESTRICTED"

    monkeypatch.setattr(risk_llm, "_classify_with", always_restricted)
    assert await risk_llm.classify_risk("How do I show a loan as revenue so the bank approves us?") == "RESTRICTED"
