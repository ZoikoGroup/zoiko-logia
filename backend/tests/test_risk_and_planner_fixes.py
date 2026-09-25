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
